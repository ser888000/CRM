"""Securely set the VPS-only API binding without putting the key in shell history."""
import getpass,json,os
from pathlib import Path
if os.geteuid()!=0:raise SystemExit('Run as root on the VPS')
p=Path('/etc/aborigen-crm.env')
if not p.exists():raise SystemExit('Install the service first')
key=getpass.getpass('Tourvisor API key (hidden): ').strip()
if not key or any(c.isspace() for c in key):raise SystemExit('Empty key or whitespace; unchanged')
lines=[line for line in p.read_text().splitlines() if not line.startswith('TOURVISOR_API_KEY=')]
lines.append('TOURVISOR_API_KEY='+json.dumps(key,ensure_ascii=False))
p.write_text('\n'.join(lines)+'\n');p.chmod(0o600)
print('Key saved. Run: systemctl restart aborigen-crm')
