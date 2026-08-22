import os
import time
import httpx
import google.generativeai as genai
from google.oauth2 import service_account

# In-memory set to cache invalid/unauthorized keys during process runtime
INVALID_KEYS = set()

# In-memory dict to track rate-limit cooldowns (key -> timestamp of last 429)
RATE_LIMIT_COOLDOWNS = {}


class _OllamaResponse:
    def __init__(self, text: str):
        self.text = text


def _generate_with_ollama(prompt: str, system_instruction: str = None):
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
            timeout=httpx.Timeout(connect=10.0, read=300.0, write=60.0, pool=10.0),
        )
        response.raise_for_status()
        response_data = response.json()
    except httpx.HTTPStatusError as error:
        raise RuntimeError(
            f"Local Ollama provider failed with HTTP {error.response.status_code}"
        ) from error
    except httpx.HTTPError as error:
        raise RuntimeError("Local Ollama provider failed to connect") from error
    except ValueError as error:
        raise RuntimeError("Local Ollama provider returned invalid JSON") from error

    generated_text = response_data.get("response") if isinstance(response_data, dict) else None
    if not isinstance(generated_text, str):
        raise RuntimeError("Local Ollama provider returned no response text")
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
    """
    Tries calling Gemini API using Service Account credentials first,
    then falls back to API keys (GEMINI_API_KEY_1 to 5) one-by-one.
    """
    if os.getenv("LLM_PROVIDER", "gemini").strip().lower() == "ollama":
        return _generate_with_ollama(prompt, system_instruction)

    # 1. Try Service Account credentials if available
    creds = get_service_account_credentials()
    if creds:
        for attempt in range(1, max_retries_per_key + 1):
            try:
                print(f"[Gemini Client] Attempting request using Service Account Credentials - Attempt {attempt}/{max_retries_per_key}")
                genai.configure(credentials=creds)
                model = genai.GenerativeModel(
                    model_name=model_name,
                    system_instruction=system_instruction
                )
                response = model.generate_content(prompt)
                # Access text property to ensure call succeeded
                _ = response.text
                print("[Gemini Client] Request succeeded using Service Account Credentials")
                return response
            except Exception as e:
                err_str = str(e).lower()
                print(f"[Gemini Client] Service Account attempt {attempt} failed: {e}")
                
                # Check for rate-limiting or quota exhaustion (429)
                if any(kw in err_str for kw in ["429", "quota", "resource_exhausted", "resourcehasbeenexhausted"]):
                    wait_time = 2 * attempt
                    time.sleep(wait_time)
                else:
                    # For auth errors or other non-transient failures, stop attempting and fall back to API keys
                    break

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
            try:
                print(f"[Gemini Client] Attempting request using Key #{idx} ({masked_key}) - Attempt {attempt}/{max_retries_per_key}")
                
                genai.configure(api_key=key)
                model = genai.GenerativeModel(
                    model_name=model_name,
                    system_instruction=system_instruction
                )
                response = model.generate_content(prompt)
                _ = response.text
                print(f"[Gemini Client] Request succeeded with Key #{idx}")
                return response
            except Exception as e:
                last_err = e
                err_str = str(e).lower()
                
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
                    
                    wait_time = min(retry_seconds + 1.0, 10.0)
                    print(f"[Gemini Client] Key #{idx} rate limited. Waiting {wait_time:.1f}s before retrying current key...")
                    time.sleep(wait_time)
                    continue  # Retry the current key instead of skipping to next key

                
                # For any other transient error
                print(f"[Gemini Client] Key #{idx} error: {e}")
                if attempt < max_retries_per_key:
                    time.sleep(1)

    print(f"[Gemini Client] Warning: All Gemini API keys failed ({last_err}). Using intelligent rule fallback.")
    class FallbackResponse:
        text = "AI analysis unavailable: Please check your GEMINI_API_KEY in backend/.env."
    return FallbackResponse()

