import os
import sys
import subprocess
from github import Github, GithubException

# Reconfigure console streams to use UTF-8 on Windows
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

TOKEN = os.getenv("GITHUB_TOKEN")
REPO_NAME = "demo-broken-app"
CWD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo-broken-app")

try:
    if not TOKEN:
        raise ValueError("GITHUB_TOKEN environment variable is required")
    print("[1/3] Connecting to GitHub...")
    g = Github(TOKEN)
    user = g.get_user()
    username = user.login
    print(f"Connected as: {username}")
    
    print(f"[2/3] Creating repository '{REPO_NAME}' on GitHub...")
    try:
        repo = user.create_repo(REPO_NAME, private=False, description="Buggy React demo application for RepoGuardian")
        print(f"Created repository: {repo.html_url}")
    except GithubException as e:
        if e.status == 422: # Repository already exists
            print("Repository already exists on GitHub, using it.")
            repo = g.get_repo(f"{username}/{REPO_NAME}")
        else:
            raise e
            
    print("[3/3] Initializing local git repository and pushing...")
    
    # Initialize git if not already initialized
    if not os.path.exists(os.path.join(CWD, ".git")):
        subprocess.run(["git", "init"], cwd=CWD, shell=True)
        
    subprocess.run(["git", "add", "."], cwd=CWD, shell=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=CWD, shell=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=CWD, shell=True)
    
    remote_url = f"https://github.com/{username}/{REPO_NAME}.git"
    
    # Check if remote exists
    remotes = subprocess.run(["git", "remote"], cwd=CWD, capture_output=True, text=True, shell=True).stdout
    if "origin" in remotes:
        subprocess.run(["git", "remote", "set-url", "origin", remote_url], cwd=CWD, shell=True)
    else:
        subprocess.run(["git", "remote", "add", "origin", remote_url], cwd=CWD, shell=True)
        
    print("Pushing code to GitHub (main branch)...")
    push_result = subprocess.run(["git", "push", "-u", "origin", "main"], cwd=CWD, capture_output=True, text=True, shell=True)
    
    if push_result.returncode == 0:
        print("\n🎉 SUCCESS!")
        print(f"Your demo repository is live at: https://github.com/{username}/{REPO_NAME}")
        print("Copy this link and scan it in your RepoGuardian local website!")
    else:
        print(f"\n❌ Git Push failed: {push_result.stderr}")
        
except Exception as e:
    print(f"\n❌ Error occurred: {e}")
