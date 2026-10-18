#!/bin/sh
set -eu

# template에 env 문자열을 직접 삽입하지 않는다. 운영의 단일 IPv4/CIDR만 지원한다.
value="${TRANSPORT_EXPORT_CONSUMER_CIDR:-}"
if [ -n "$value" ]; then
    case "$value" in *[!0-9./]*) echo "Invalid export consumer IPv4/CIDR" >&2; exit 2;; esac
    printf '%s\n' "$value" | awk '
        NR != 1 { exit 1 }
        {
            n = split($0, parts, "/")
            if (n > 2 || split(parts[1], octets, ".") != 4) exit 1
            for (i=1; i<=4; i++) {
                if (octets[i] !~ /^[0-9]+$/ || length(octets[i]) > 3 ||
                    (length(octets[i]) > 1 && substr(octets[i],1,1) == "0") ||
                    octets[i] + 0 > 255) exit 1
            }
            if (n == 2 && (parts[2] !~ /^[0-9]+$/ || length(parts[2]) > 2 ||
                (length(parts[2]) > 1 && substr(parts[2],1,1) == "0") ||
                parts[2] + 0 > 32)) exit 1
        }
    ' || { echo "Invalid export consumer IPv4/CIDR" >&2; exit 2; }
fi
# 소유 Nginx container 안에서만 생성하며 invalid 값은 기존 파일도 덮어쓰지 않는다.
{
    if [ -n "$value" ]; then printf 'allow %s;\n' "$value"; fi
    printf 'deny all;\n'
} > /etc/nginx/transport-export-allow.conf
