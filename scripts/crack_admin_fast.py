import hashlib, secrets

target_hash = 'pbkdf2_sha256$100000$c985f99e67d2ab8e2de1d1ddfe115225$52c1b3a60d537f84c4e482448181b33c9dfb4727fb80741dddfbe64ee42c1e1c'
parts = target_hash.split('$')
iters = int(parts[1])
salt = parts[2]
expected = parts[3]

candidates = [
    'Anmol2005@', 'Anmol@2005!', 'Anmol#2005', 'anmol@123', 'anmol', 'anmol123', 'anmol1234',
    'Anmol123', 'Anmol1234', 'Anmol@05', 'anmol05', 'Anmol', 'ANMOL',
    'Admin@2005', 'admin@2005', 'admin2005', 'Admin2005', 'Admin2005@',
    'nexus@2026', 'nexus@2025', 'NexusNode@123', 'NexusNode@1234', 'Nexus@123', 'nexus123',
    'tecno', 'Tecno@123', 'Tecno@1234', 'Tecno@2025', 'Tecno@2026', 'BG6', 'bg6', 'BG6@123', 'BG6@1234',
    'sap123', 'sap1234', 'sappassword', 'UPES@2025', 'UPES@2026', 'Upes@2025', 'Upes@2026', 'Upes@1234', 'Upes@123',
    '500122941@upes', '500122941@stu.upes.ac.in', 'anmol.2005', 'Anmol.2005',
    'Admin', 'admin', 'ADMIN', 'Admin@1', 'Admin@12', 'Admin@123456', 'Admin!@#$',
    'admin@nexus', 'Admin@Nexus', 'NexusAdmin', 'nexusadmin', 'NexusAdmin@123', 'NexusAdmin@1234',
    'superadmin', 'Superadmin@123', 'Superadmin@1234', 'P@ssword1', 'P@ssw0rd1', 'Password@1',
    'Nexus2026', 'Nexus2025', 'nexusnode@123', 'nexusnode@1234', 'bg6@2026'
]

print(f"Testing {len(candidates)} candidates on local fast CPU...")
for c in candidates:
    digest = hashlib.pbkdf2_hmac('sha256', c.encode('utf-8'), salt.encode('utf-8'), iters).hex()
    if digest == expected:
        print(f"!!! MATCH FOUND !!! -> '{c}'")
        break
else:
    print("No match in expanded candidate list.")
