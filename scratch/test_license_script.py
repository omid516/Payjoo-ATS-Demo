import sys
import os

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generate_license import generate_license_key
from apps.core.license import verify_license_key

def test():
    print("Generating a test key...")
    # Gen key
    key = generate_license_key(
        licensee="شرکت نمونه",
        expires_at="2027-12-31",
        max_jobs=10,
        max_candidates=100,
        max_posts=20,
        allowed_domains=["ats.company.com"]
    )
    print(f"Key: {key}\n")

    print("Verifying key on correct domain...")
    res = verify_license_key(key, current_host="ats.company.com")
    print(f"Result (ats.company.com): {res}\n")

    print("Verifying key on localhost (dev)...")
    res_local = verify_license_key(key, current_host="localhost")
    print(f"Result (localhost): {res_local}\n")

    print("Verifying key on incorrect domain...")
    res_wrong = verify_license_key(key, current_host="another.com")
    print(f"Result (another.com): {res_wrong}\n")

    print("Verifying key with expired date...")
    expired_key = generate_license_key(
        licensee="شرکت نمونه",
        expires_at="2020-01-01",
        max_jobs=10,
        max_candidates=100,
        max_posts=20,
        allowed_domains=[]
    )
    res_expired = verify_license_key(expired_key)
    print(f"Result (expired): {res_expired}\n")

if __name__ == '__main__':
    test()
