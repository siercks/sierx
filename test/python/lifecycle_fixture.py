"""Public fixture checkpoint for deployment tests; no production credentials."""
import hashlib,hmac,json

def configure_lifecycle(home,app):
    directory=home/".local/share/sierx/lifecycle/guard"
    directory.mkdir(parents=True,exist_ok=True,mode=0o700);directory.chmod(0o700)
    key=bytes(range(32))
    head={"instance_id":"18000000-0000-7000-8000-000000000001","sequence":0,"hash":""}
    head["mac"]=hmac.new(key,json.dumps(head,separators=(",",":")).encode(),hashlib.sha256).hexdigest()
    (directory/"checkpoint.json").write_text(json.dumps(head));(directory/"checkpoint.json").chmod(0o600)
    (directory/"verification.key").write_bytes(key);(directory/"verification.key").chmod(0o600)
    with app.open("a") as f:
        f.write("SIERX_LIFECYCLE_CHECKPOINT=/var/lib/sierx/lifecycle/guard/checkpoint.json\nSIERX_LIFECYCLE_GUARD_KEY_FILE=/var/lib/sierx/lifecycle/guard/verification.key\n")
