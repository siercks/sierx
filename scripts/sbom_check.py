"""Validate sierx's generated CycloneDX subset and compare all stable fields.

This is deliberately not a general-purpose CycloneDX schema validator.
Fresh output is the expected shape; only UUID and timestamp may differ.
"""
import datetime
import json
import sys
import uuid


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def normalize(document):
    if not isinstance(document, dict):
        raise ValueError("expected an object")
    if document.get("bomFormat") != "CycloneDX" or document.get("specVersion") != "1.5":
        raise ValueError("expected CycloneDX 1.5")
    if type(document.get("version")) is not int or document["version"] != 1:
        raise ValueError("expected document version 1")
    serial = document.get("serialNumber", "")
    if not isinstance(serial, str) or not serial.startswith("urn:uuid:"):
        raise ValueError("missing UUID serialNumber")
    uuid.UUID(serial[9:])
    metadata = document.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("missing metadata")
    timestamp = metadata.get("timestamp", "")
    if not isinstance(timestamp, str) or not timestamp.endswith("Z"):
        raise ValueError("timestamp must use UTC Z suffix")
    datetime.datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
    components = document.get("components")
    if not isinstance(components, list) or not components:
        raise ValueError("missing component inventory")
    refs = set()
    for component in components:
        if not isinstance(component, dict) or not isinstance(component.get("bom-ref"), str):
            raise ValueError("component missing bom-ref")
        if component["bom-ref"] in refs:
            raise ValueError("duplicate component bom-ref")
        refs.add(component["bom-ref"])
    # Copy before deleting nondeterministic fields; caller objects stay intact.
    normalized = json.loads(json.dumps(document))
    del normalized["serialNumber"]
    del normalized["metadata"]["timestamp"]
    normalized["components"].sort(key=lambda c: c["bom-ref"])
    return normalized


def check(existing, fresh):
    if normalize(existing) != normalize(fresh):
        raise ValueError("SBOM content is stale or malformed; regenerate with make sbom")


if __name__ == "__main__":
    try:
        with open(sys.argv[1], encoding="utf-8") as source:
            existing = json.load(source, object_pairs_hook=unique_object)
        with open(sys.argv[2], encoding="utf-8") as source:
            fresh = json.load(source, object_pairs_hook=unique_object)
        check(existing, fresh)
    except (ValueError, TypeError, KeyError, OSError) as error:
        sys.exit("sbom-check: " + str(error))
    print("sbom-check: current inventory, licenses, hashes and build metadata verified")
