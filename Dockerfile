FROM ubuntu:22.04

ARG HUGO=0.101.0

ARG UNAME=builder
ARG UID=1000
ARG GID=1000

RUN : \
    && groupadd -g $GID -o $UNAME \
    && useradd -m -u $UID -g $GID -o -s /bin/bash $UNAME \
    && apt-get update -q \
    && apt-get install -q -y make nodejs npm wget git rsync python3-pip \
    && wget -O hugo.deb https://github.com/gohugoio/hugo/releases/download/v${HUGO}/hugo_extended_${HUGO}_Linux-64bit.deb \
    && dpkg -i hugo.deb \
    && rm hugo.deb \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m pip install --no-cache-dir arxiv requests unidecode ujson \
    && :

USER $UNAME

WORKDIR /src