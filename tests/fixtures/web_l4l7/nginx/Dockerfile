# nginx serving two virtual hosts:
#   - server.local on :443         with a valid self-signed cert
#   - tls-broken.local on :4443    with an *expired* self-signed cert
#
# Certificates are generated at container start so they always have
# the right "now" relative to wallclock; expired one is dated 2020.

FROM nginx:1.27-alpine

# python3 + cryptography lets us mint certificates with arbitrary
# not_before / not_after dates, which is the whole point.
RUN apk add --no-cache python3 py3-cryptography

COPY nginx.conf /etc/nginx/nginx.conf
COPY gen_certs.py /usr/local/bin/gen_certs.py
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/gen_certs.py

EXPOSE 443 4443
CMD ["/usr/local/bin/entrypoint.sh"]
