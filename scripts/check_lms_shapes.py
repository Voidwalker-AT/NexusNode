import paramiko
import json

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.WarningPolicy())
ssh.connect('192.168.29.21', port=8022, username='u0_a208', key_filename=os.environ.get("BG6_SSH_KEY", os.path.expanduser("~/.ssh/nexusnode_bg6_ed25519")) if os.path.exists(os.path.expanduser("~/.ssh/nexusnode_bg6_ed25519")) else None, password=os.environ.get("BG6_SSH_PASSWORD"))

remote_script = '''
import app, json
courses = app.lms_service.list_courses('admin', {})
print("=== COURSES ===")
print(json.dumps(courses.to_dict(), indent=2))
assign = app.lms_service.list_assignments('admin', {})
print("=== ASSIGNMENTS ===")
print(json.dumps(assign.to_dict(), indent=2))
'''

sftp = ssh.open_sftp()
with sftp.file('/data/data/com.termux/files/home/server/test_lms_shapes.py', 'w') as f:
    f.write(remote_script)
sftp.close()

stdin, stdout, stderr = ssh.exec_command('export PATH=/data/data/com.termux/files/usr/bin:$PATH; cd ~/server && python test_lms_shapes.py && rm test_lms_shapes.py')
print(stdout.read().decode('utf-8', errors='replace'))
err = stderr.read().decode('utf-8', errors='replace')
if err: print('STDERR:', err)
ssh.close()
