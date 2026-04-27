FROM alpine:3.20

RUN apk add --no-cache dnsmasq

COPY dnsmasq.conf /etc/dnsmasq.conf

EXPOSE 53/udp
# `-k` keeps dnsmasq in the foreground so docker sees the process.
# `--log-facility=-` sends logs to stderr, which `docker logs` captures.
CMD ["dnsmasq", "-k", "--conf-file=/etc/dnsmasq.conf"]
