"""Bounded public HTTPS requests with DNS pinning, TLS verification and no redirects."""
import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit

import httpx


def public_url(value):
    try:
        url = urlsplit(value)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.port not in (None, 443) or url.fragment:
            raise ValueError()
        host = url.hostname.encode("idna").decode("ascii")
        if host in ("localhost",) or host.endswith((".local", ".internal", ".localhost")):
            raise ValueError()
        return url, host
    except (ValueError, UnicodeError):
        raise ValueError("Нужен публичный HTTPS-адрес без логина, пароля и нестандартного порта") from None


async def public_request(method, url, *, headers=None, payload=None, limit=2000000, timeout=30, allow_private=False):
    parsed, host = public_url(url)
    try:addresses = await asyncio.wait_for(asyncio.to_thread(socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM), 5)
    except socket.gaierror:raise httpx.ConnectError('DNS внешнего сервиса недоступен') from None
    ips = list(dict.fromkeys(a[4][0] for a in addresses))
    def permitted(value):
        address = ipaddress.ip_address(value)
        return address.is_global or (allow_private and address.is_private and not
            (address.is_loopback or address.is_link_local or address.is_reserved or address.is_unspecified or address.is_multicast))
    if not ips or any(not permitted(ip) for ip in ips):
        raise ValueError("Запросы к локальным и служебным сетям запрещены")
    # Prefer IPv4 on VPS installations without IPv6 routing. Fail over only for a
    # connection failure BEFORE a response; never replay a paid POST after a read
    # timeout or partial response. All addresses were checked before any request.
    ips.sort(key=lambda value:(':' in value))
    async with asyncio.timeout(timeout):
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            for index,ip in enumerate(ips[:3]):
                netloc = "[" + ip + "]" if ":" in ip else ip
                pinned = urlunsplit(("https", netloc, parsed.path or "/", parsed.query, ""))
                try:
                    async with client.stream(method,pinned,headers={**(headers or {}),"Host":host,"Accept-Encoding":"identity"},json=payload,
                                             extensions={"sni_hostname":host}) as response:
                        if response.headers.get("content-encoding","identity").lower()!='identity':raise ValueError('Сжатые ответы внешнего сервиса не поддерживаются')
                        data=bytearray()
                        async for chunk in response.aiter_raw(chunk_size=65536):
                            data.extend(chunk)
                            if len(data)>limit:raise ValueError('Ответ внешнего сервиса слишком большой')
                        return response.status_code,dict(response.headers),bytes(data)
                except httpx.ConnectError:
                    if index==len(ips[:3])-1:raise
