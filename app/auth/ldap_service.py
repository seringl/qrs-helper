"""LDAPS authentication — DESIGN.md §7.3/§7.4.

Must-have feature, but tested only in a production deployment with a
directory server. Demo mode keeps LDAP_ENABLED=false.
"""
import os
import socket
import time

_availability_cache = {"checked": 0.0, "available": False}
CACHE_SECONDS = 60


def is_enabled():
    return os.environ.get("LDAP_ENABLED", "false").strip().lower() == "true"


def is_available():
    """Cheap reachability probe (cached) so the login page can grey out
    directory login during an outage (§7.4)."""
    if not is_enabled():
        return False
    now = time.monotonic()
    if now - _availability_cache["checked"] < CACHE_SECONDS:
        return _availability_cache["available"]
    host = os.environ.get("LDAP_SERVER", "")
    port = int(os.environ.get("LDAP_PORT", "636"))
    ok = False
    if host:
        try:
            with socket.create_connection((host, port), timeout=2):
                ok = True
        except OSError:
            ok = False
    _availability_cache.update(checked=now, available=ok)
    return ok


def authenticate(username, password):
    """Verify directory credentials. Returns a dict of user attributes on
    success, None on bad credentials. Raises RuntimeError on config/server
    problems so callers can distinguish outage from bad password."""
    import ldap3  # deferred import; only needed when LDAP is enabled

    host = os.environ.get("LDAP_SERVER")
    if not host:
        raise RuntimeError("LDAP_SERVER is not configured")
    port = int(os.environ.get("LDAP_PORT", "636"))
    use_ssl = os.environ.get("LDAP_USE_SSL", "true").strip().lower() == "true"
    attr_user = os.environ.get("LDAP_USER_ATTR_USERNAME", "sAMAccountName")
    attr_mail = os.environ.get("LDAP_USER_ATTR_EMAIL", "mail")
    attr_name = os.environ.get("LDAP_USER_ATTR_NAME", "displayName")
    search_base = os.environ.get("LDAP_USER_SEARCH_BASE", "")
    allowed_group = os.environ.get("LDAP_ALLOWED_GROUP", "").strip()

    server = ldap3.Server(host, port=port, use_ssl=use_ssl, get_info=ldap3.NONE)

    # 1) bind with the service account and find the user
    svc = ldap3.Connection(
        server,
        user=os.environ.get("LDAP_BIND_DN"),
        password=os.environ.get("LDAP_BIND_PASSWORD"),
        auto_bind=True,
        receive_timeout=10,
    )
    try:
        flt = f"({attr_user}={ldap3.utils.conv.escape_filter_chars(username)})"
        if allowed_group:
            flt = f"(&{flt}(memberOf={allowed_group}))"
        svc.search(
            search_base, flt, attributes=[attr_user, attr_mail, attr_name]
        )
        if not svc.entries:
            return None
        entry = svc.entries[0]
        user_dn = entry.entry_dn
    finally:
        svc.unbind()

    # 2) verify the user's own credentials
    try:
        user_conn = ldap3.Connection(
            server, user=user_dn, password=password, auto_bind=True,
            receive_timeout=10,
        )
        user_conn.unbind()
    except ldap3.core.exceptions.LDAPBindError:
        return None

    def _val(attr):
        try:
            v = entry[attr].value
            return v if isinstance(v, str) else (v[0] if v else None)
        except Exception:  # noqa: BLE001
            return None

    return {
        "username": _val(attr_user) or username,
        "email": _val(attr_mail),
        "display_name": _val(attr_name) or username,
    }
