import hashlib

target = 'e1756a3fc8ad9a40ca179c15372b2dc60aba41500bcb30b44ec437681e897c06'
salt = '8d1b4b376f154f9527cc7c427dd15fc1'

words = [
    'admin', 'Admin', 'Admin@1234', 'Admin@123', 'admin123', 'admin1234', 'admin@123', 'admin@1234',
    'password', 'Password', 'Password@123', 'Password@1234', 'anmol', 'anmol2005', 'Anmol2005',
    'Anmol@2005', 'Anmol@1234', 'nexus', 'Nexus', 'nexusnode', 'NexusNode', 'Nexus@1234', 'Nexus@2026',
    '12345678', '123456', '123456789', 'administrator', 'Administrator', 'root', 'toor', 'default',
    'bg6', 'BG6', 'tecno', 'Tecno', 'upes', 'UPES', 'upes1234', 'UPES@1234', 'sap', 'SAP',
    'student', 'Student', 'Student@123', '500122941', 'UPES500122941'
]

for w in words:
    # try w + salt
    if hashlib.sha256((w + salt).encode('utf-8')).hexdigest() == target:
        print(f"FOUND MATCH (w+salt): {w}")
        break
    # try salt + w
    if hashlib.sha256((salt + w).encode('utf-8')).hexdigest() == target:
        print(f"FOUND MATCH (salt+w): {w}")
        break
    # try w only
    if hashlib.sha256(w.encode('utf-8')).hexdigest() == target:
        print(f"FOUND MATCH (w only): {w}")
        break
else:
    print("No match in wordlist.")
