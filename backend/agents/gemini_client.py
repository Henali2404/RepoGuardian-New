import os
import time
import hashlib
import threading
from collections import OrderedDict
import httpx
import google.generativeai as genai
from google.oauth2 import service_account

# In-memory set to cache invalid/unauthorized keys during process runtime
INVALID_KEYS = set()

# In-memory dict to track rate-limit cooldowns (key -> timestamp of last 429)
RATE_LIMIT_COOLDOWNS = {}
MODEL_CACHE = {}
RESPONSE_CACHE = OrderedDict()
CACHE_LOCK = threading.Lock()
MODEL_LOCK = threading.Lock()
CACHE_HITS = 0
CACHE_MISSES = 0


class _OllamaResponse:
    def __init__(self, text: str):
        self.text = text


def _cache_enabled() -> bool:
    return os.getenv("LLM_CACHE_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


def _cache_key(provider: str, model_name: str, prompt: str, system_instruction: str = None) -> str:
    payload = "\0".join((provider, model_name, system_instruction or "", prompt))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_get(key: str):
    global CACHE_HITS, CACHE_MISSES
    if not _cache_enabled():
        return None
    now = time.time()
    ttl = float(os.getenv("LLM_CACHE_TTL_SECONDS", "900"))
    with CACHE_LOCK:
        cached = RESPONSE_CACHE.get(key)
        if cached and now - cached[0] <= ttl:
            RESPONSE_CACHE.move_to_end(key)
            CACHE_HITS += 1
            return _OllamaResponse(cached[1])
        if cached:
            RESPONSE_CACHE.pop(key, None)
        CACHE_MISSES += 1
    return None


def _cache_put(key: str, text: str):
    if not _cache_enabled() or not isinstance(text, str) or not text:
        return
    max_entries = max(1, int(os.getenv("LLM_CACHE_MAX_ENTRIES", "128")))
    with CACHE_LOCK:
        RESPONSE_CACHE[key] = (time.time(), text)
        RESPONSE_CACHE.move_to_end(key)
        while len(RESPONSE_CACHE) > max_entries:
            RESPONSE_CACHE.popitem(last=False)


def _log_request(provider: str, model: str, started: float, success: bool, retry: int, prompt_chars: int, response_chars: int = 0, error=None):
    event = {
        "provider": provider,
        "model": model,
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        "success": success,
        "retry": retry,
        "prompt_chars": prompt_chars,
        "response_chars": response_chars,
    }
    if error:
        event["error_type"] = type(error).__name__
        event["error_status"] = getattr(getattr(error, "response", None), "status_code", None)
    print(f"[LLM_METRIC] {event}")


def _get_gemini_model(model_name: str, system_instruction: str, auth_fingerprint: str, configure):
    cache_key = (model_name, system_instruction or "", auth_fingerprint)
    configure()
    with MODEL_LOCK:
        model = MODEL_CACHE.get(cache_key)
        if model is None:
            model = genai.GenerativeModel(model_name=model_name, system_instruction=system_instruction)
            MODEL_CACHE[cache_key] = model
        return model


def _generate_with_ollama(prompt: str, system_instruction: str = None):
    started = time.perf_counter()
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "").strip()
    if not model:
        raise RuntimeError("Local Ollama provider failed: OLLAMA_MODEL is not configured")

    combined_prompt = prompt
    if system_instruction:
        combined_prompt = (
            "System instruction:\n"
            f"{system_instruction}\n\n"
            "User prompt:\n"
            f"{prompt}"
        )

    try:
        response = httpx.post(
            f"{base_url}/api/generate",
            json={
                "model": model,
                "prompt": combined_prompt,
                "stream": False,
            },
            timeout=httpx.Timeout(
                connect=float(os.getenv("OLLAMA_CONNECT_TIMEOUT_SECONDS", "10")),
                read=float(os.getenv("OLLAMA_READ_TIMEOUT_SECONDS", "180")),
                write=60.0,
                pool=10.0,
            ),
        )
        response.raise_for_status()
        response_data = response.json()
    except httpx.HTTPStatusError as error:
        _log_request("ollama", model, started, False, 1, len(combined_prompt), error=error)
        raise RuntimeError(
            f"Local Ollama provider failed with HTTP {error.response.status_code}"
        ) from error
    except httpx.HTTPError as error:
        _log_request("ollama", model, started, False, 1, len(combined_prompt), error=error)
        raise RuntimeError("Local Ollama provider failed to connect") from error
    except ValueError as error:
        _log_request("ollama", model, started, False, 1, len(combined_prompt), error=error)
        raise RuntimeError("Local Ollama provider returned invalid JSON") from error

    generated_text = response_data.get("response") if isinstance(response_data, dict) else None
    if not isinstance(generated_text, str):
        raise RuntimeError("Local Ollama provider returned no response text")
    _log_request("ollama", model, started, True, 1, len(combined_prompt), len(generated_text))
    return _OllamaResponse(generated_text)

def get_service_account_credentials():
    """
    Tries to load service account credentials from GOOGLE_APPLICATION_CREDENTIALS,
    GEMINI_SERVICE_ACCOUNT_JSON, or a local service_account.json file.
    """
    json_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("GEMINI_SERVICE_ACCOUNT_JSON") or "service_account.json"
    
    # If the path is relative, try to resolve it relative to backend/ directory
    if json_path and not os.path.isabs(json_path):
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidate = os.path.join(backend_dir, json_path)
        if os.path.exists(candidate):
            json_path = candidate
            
    if json_path and os.path.exists(json_path):
        try:
            return service_account.Credentials.from_service_account_file(json_path)
        except Exception as e:
            print(f"[Gemini Client] Failed to load service account credentials from {json_path}: {e}")
    return None

def generate_content_with_fallback(
    prompt: str,
    model_name: str = "gemini-flash-latest",
    system_instruction: str = None,
    max_retries_per_key: int = 3
):
    """Call the configured provider while preserving the response.text contract."""
    provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    provider_model = os.getenv("OLLAMA_MODEL", "").strip() if provider == "ollama" else model_name
    key = _cache_key(provider, provider_model, prompt, system_instruction)
    cached = _cache_get(key)
    if cached:
        print(f"[LLM_METRIC] cache_hit provider={provider} model={provider_model} prompt_chars={len(prompt)}")
        return cached

    if provider == "ollama":
        response = _generate_with_ollama(prompt, system_instruction)
        _cache_put(key, response.text)
        return response

    # 1. Try Service Account credentials if available
    creds = get_service_account_credentials()
    if creds:
        for attempt in range(1, max_retries_per_key + 1):
            started = time.perf_counter()
            try:
                model = _get_gemini_model(
                    model_name, system_instruction, "service-account",
                    lambda: genai.configure(credentials=creds),
                )
                response = model.generate_content(prompt)
                text = response.text
                _log_request("gemini-service-account", model_name, started, True, attempt, len(prompt), len(text))
                _cache_put(key, text)
                return response
            except Exception as e:
                err_str = str(e).lower()
                _log_request("gemini-service-account", model_name, started, False, attempt, len(prompt), error=e)
                if not any(kw in err_str for kw in ["429", "quota", "resource_exhausted", "timeout", "temporarily", "unavailable", "503"]):
                    break
                time.sleep(min(0.5 * (2 ** (attempt - 1)), 3.0))

    # 2. Fall back to API keys if Service Account is not configured or fails

    keys = []
    for i in range(1, 6):
        key = os.getenv(f"GEMINI_API_KEY_{i}")
        if key and key.strip() and "your_gemini_api_key" not in key:
            keys.append(key.strip())
            
    default_key = os.getenv("GEMINI_API_KEY")
    if default_key and default_key.strip():
        keys.append(default_key.strip())
        
    # Filter out duplicates and keys previously flagged as invalid
    unique_keys = []
    for k in keys:
        if k not in unique_keys and k not in INVALID_KEYS:
            unique_keys.append(k)
            
    # Filter out keys currently in rate-limit cooldown (60 seconds)
    now = time.time()
    active_keys = [k for k in unique_keys if now - RATE_LIMIT_COOLDOWNS.get(k, 0) > 60]
    
    # If all keys are in cooldown, reset active_keys to unique_keys as fallback
    if not active_keys:
        active_keys = unique_keys
        
    if not active_keys:
        raise ValueError("No valid Gemini API keys found. Please set GEMINI_API_KEY_1 in your .env file.")
        
    last_err = None
    
    for idx, key in enumerate(active_keys, 1):
        masked_key = f"{key[:6]}...{key[-4:]}" if len(key) > 10 else "..."
        
        for attempt in range(1, max_retries_per_key + 1):
            started = time.perf_counter()
            try:
                print(f"[Gemini Client] Attempting request using Key #{idx} ({masked_key}) - Attempt {attempt}/{max_retries_per_key}")
                model = _get_gemini_model(
                    model_name, system_instruction, hashlib.sha256(key.encode()).hexdigest(),
                    lambda: genai.configure(api_key=key),
                )
                response = model.generate_content(prompt)
                text = response.text
                _log_request("gemini-api-key", model_name, started, True, attempt, len(prompt), len(text))
                _cache_put(key=_cache_key("gemini", model_name, prompt, system_instruction), text=text)
                print(f"[Gemini Client] Request succeeded with Key #{idx}")
                return response
            except Exception as e:
                last_err = e
                err_str = str(e).lower()
                _log_request("gemini-api-key", model_name, started, False, attempt, len(prompt), error=e)
                
                # Check for authentication/authorization errors (401, deleted service account, invalid key)
                if any(kw in err_str for kw in ["401", "unauthenticated", "api_key_invalid", "deleted or disabled", "invalid authentication"]):
                    print(f"[Gemini Client] Key #{idx} ({masked_key}) is invalid/unauthorized: {e}")
                    INVALID_KEYS.add(key)
                    break  # Stop retrying this key; move to next key immediately
                    
                # Check for rate-limiting or quota exhaustion (429, resource exhausted)
                if any(kw in err_str for kw in ["429", "quota", "resource_exhausted", "resourcehasbeenexhausted"]):
                    # If it's a permanent daily quota exhaustion, skip immediately
                    if any(kw in err_str for kw in ["exceeded your current quota", "billing details", "freetier", "daily limit"]):
                        print(f"[Gemini Client] Key #{idx} daily quota is fully exhausted. Skipping to next key immediately...")
                        RATE_LIMIT_COOLDOWNS[key] = time.time()
                        break

                    import re
                    retry_seconds = 5.0
                    match = re.search(r"retry in ([\d\.]+)s", err_str)
                    if match:
                        try:
                            retry_seconds = float(match.group(1))
                        except ValueError:
                            pass
                    else:
                        match_sec = re.search(r"seconds:\s*(\d+)", err_str)
                        if match_sec:
                            try:
                                retry_seconds = float(match_sec.group(1))
                            except ValueError:
                                pass
                    
                    wait_time = min(retry_seconds, float(os.getenv("GEMINI_MAX_RETRY_DELAY_SECONDS", "8")))
                    print(f"[Gemini Client] Key #{idx} rate limited. Waiting {wait_time:.1f}s before retrying current key...")
                    time.sleep(wait_time)
                    continue  # Retry the current key instead of skipping to next key

                
                # For any other transient error
                print(f"[Gemini Client] Key #{idx} error: {e}")
                if attempt < max_retries_per_key:
                    time.sleep(min(0.5 * (2 ** (attempt - 1)), 3.0))

    print(f"[Gemini Client] Warning: All Gemini API keys failed ({last_err}). Using intelligent rule fallback.")
    class FallbackResponse:
        text = "AI analysis unavailable: Please check your GEMINI_API_KEY in backend/.env."
    return FallbackResponse()

