"""Run with `python tests/production_smoke.py tally:test` after building the image.

Only UUID-named containers/volumes created here are removed. No Compose up/down,
existing volumes, host ports, real environment files or Traefik network are used.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import uuid


ROOT = Path(__file__).resolve().parent.parent
IMAGE = sys.argv[1] if len(sys.argv) > 1 else "tally:test"
PROBE = (ROOT / "tests/production_probe.py").read_text()
PREFIX = "tally-ci-" + uuid.uuid4().hex


def docker(*args, **kwargs):
    return subprocess.run(["docker", *args], cwd=ROOT, check=True, text=True, **kwargs)


def render(identifier, project):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("TALLY_", "DJANGO_", "TRAEFIK_", "COMPOSE_"))}
    env.update(DJANGO_SECRET_KEY="fictional-secret-" + project,
               TALLY_HOST=project + ".example.invalid", TRAEFIK_NETWORK="fictional-proxy")
    if identifier is not None:
        env["TALLY_TRAEFIK_ID"] = identifier
    # Exercise the documented optional override syntax as well as base routing.
    override = '''services:
  app:
    labels:
      - "traefik.http.routers.${TALLY_TRAEFIK_ID:-tally}.tls.certresolver=fictional-resolver"
      - "traefik.http.routers.${TALLY_TRAEFIK_ID:-tally}.middlewares=fictional-auth@file"
'''
    return json.loads(docker("compose", "--env-file", "/dev/null", "-p", project,
                             "-f", "compose.yaml", "-f", "compose.prod.yaml", "-f", "-",
                             "config", "--format", "json", input=override,
                             env=env, capture_output=True).stdout)


configs = [render(None, "fictional-a"), render("portfolio-b", "fictional-b")]
routing_sets = []
for config, identifier, project in zip(configs, ["tally", "portfolio-b"], ["fictional-a", "fictional-b"]):
    app = config["services"]["app"]
    assert not app.get("ports")
    labels = app["labels"]
    router = f"traefik.http.routers.{identifier}"
    assert labels[router + ".rule"] == f'Host("{project}.example.invalid")'
    assert labels[router + ".service"] == identifier
    assert labels[router + ".tls"] == "true"
    assert labels[router + ".tls.certresolver"] == "fictional-resolver"
    assert labels[router + ".middlewares"] == "fictional-auth@file"
    assert labels["traefik.docker.network"] == "fictional-proxy"
    assert labels[f"traefik.http.services.{identifier}.loadbalancer.server.port"] == "8000"
    routing_sets.append({key for key in labels if key.startswith("traefik.http.")})
assert routing_sets[0].isdisjoint(routing_sets[1])
for volume in ["tally-data", "tally-backups"]:
    assert configs[0]["volumes"][volume]["name"] != configs[1]["volumes"][volume]["name"]
assert configs[0]["services"]["app"]["environment"]["DJANGO_SECRET_KEY"] != configs[1]["services"]["app"]["environment"]["DJANGO_SECRET_KEY"]
print("Two independent production routing configurations passed.", flush=True)

environment = configs[0]["services"]["app"]["environment"]
environment.update(DJANGO_ALLOWED_HOSTS="smoke.example.invalid",
                   DJANGO_CSRF_TRUSTED_ORIGINS="https://smoke.example.invalid")
env_args = [arg for key, value in environment.items() for arg in ("-e", f"{key}={value}")]
volumes = []
containers = []


def probe(container, mode):
    docker("exec", "-i", container, "python", "-", mode, input=PROBE)


try:
    # Validation happens before migrations/Gunicorn and cannot silently invent labels.
    for invalid in ["bad.id", "bad@docker", "Uppercase", "-leading", "x" * 64]:
        result = subprocess.run(["docker", "run", "--rm", *env_args,
                                 "-e", "TALLY_TRAEFIK_ID=" + invalid, "--entrypoint", "python",
                                 IMAGE, "-c", "import config.settings"], text=True, capture_output=True)
        assert result.returncode != 0 and "TALLY_TRAEFIK_ID must be" in result.stderr
    for suffix in ["source", "backups", "restored"]:
        name = PREFIX + "-" + suffix
        docker("volume", "create", name, stdout=subprocess.DEVNULL)
        volumes.append(name)
    source, backups, restored = volumes
    for volume, mode in [(source, "seed"), (restored, "restored")]:
        if mode == "restored":
            docker("run", "--rm", "-i", "--user", "0:0", "-v", f"{backups}:/backups:ro",
                   "-v", f"{restored}:/data", "--entrypoint", "python", IMAGE, "-", "restore", input=PROBE)
        name = PREFIX + "-" + mode
        containers.append(name)
        docker("run", "-d", "--name", name, *env_args, "-v", f"{volume}:/data",
               "-v", f"{backups}:/backups", IMAGE, stdout=subprocess.DEVNULL)
        probe(name, mode)
        if mode == "seed":
            probe(name, "backup")
            docker("stop", name, stdout=subprocess.DEVNULL)
    print("Production-image backup integrity and restored login/data passed.", flush=True)
except BaseException:
    for name in containers:
        subprocess.run(["docker", "logs", "--tail", "80", name], check=False)
    raise
finally:
    for name in containers:
        subprocess.run(["docker", "rm", "-f", name], check=False, stdout=subprocess.DEVNULL)
    for name in volumes:
        subprocess.run(["docker", "volume", "rm", name], check=False, stdout=subprocess.DEVNULL)
