import paramiko

s = paramiko.SSHClient()
s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
s.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005')

cmd = """python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.connect(('8.8.8.8', 80))
print('BG6_IP:' + s.getsockname()[0])
s.close()
"
"""
stdin, stdout, stderr = s.exec_command(cmd)
print(stdout.read().decode().strip())
s.close()
