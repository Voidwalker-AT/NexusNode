import hashlib
import secrets

stored_hash = 'pbkdf2_sha256$100000$c985f99e67d2ab8e2de1d1ddfe115225$52c1b3a60d537f84c4e482448181b33c9dfb4727fb80741dddfbe64ee42c1e1c'
parts = stored_hash.split('$')
_, iters_str, salt_part, expected_digest = parts

test_passwords = ['Admin@1234', 'admin', 'adminpassword', 'anmol2005', 'nexusnode', 'Admin@123', 'admin123']

for p in test_passwords:
    computed = hashlib.pbkdf2_hmac('sha256', p.encode('utf-8'), salt_part.encode('utf-8'), int(iters_str)).hex()
    if computed == expected_digest:
        print(f"MATCH FOUND: '{p}'")
        break
else:
    print("No match found in candidate list")
