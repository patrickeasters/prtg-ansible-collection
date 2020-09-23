# Ansible Collection - patrickeasters.prtg

An Ansible collection containing a single module `prtg` for adding/removing devices in PRTG as well as pausing/unpausing them.

Example module usage:
```yaml
- prtg:  prtg_url="https://prtg.example.com/" 
         api_user=ansible_api
         api_passhash=1234567890
         device_name=myhost.example.com
         clone_from=1234
         dest_group=5678
         state=present
         enabled=yes
```