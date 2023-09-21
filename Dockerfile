FROM ubuntu:23.04

# Meta labels
LABEL maintainer="Gregor Cerar <gregor.cerar@ijs.si>"

ARG UNAME=builder
ARG UID=1000
ARG GID=1000

# Suppress any manual intervention, while configuring packets
ARG DEBIAN_FRONTEND=noninteractive

# Hugo version
ARG HUGO=0.117.0

# Speedup Python
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Make RUN commands use `bash --login`:
SHELL ["/bin/bash", "--login", "-c"]

WORKDIR /src

RUN : \
    && groupadd -g $GID -o $UNAME \
    && useradd -m -u $UID -g $GID -o -s /bin/bash $UNAME \
    && apt-get update -q \
    && apt-get install -q -y --no-install-recommends make nodejs npm wget git rsync python3-pip \
    && wget -O hugo.deb https://github.com/gohugoio/hugo/releases/download/v${HUGO}/hugo_extended_${HUGO}_linux-amd64.deb \
    && dpkg -i hugo.deb \
    && rm hugo.deb \
    && rm -rf /var/lib/apt/lists/* \
    && :

USER ${UID}:${GID}

ENV PATH="${PATH}:/home/${UNAME}/.local/bin"

RUN python3 -m pip install --user --no-cache-dir --break-system-packages arxiv requests unidecode ujson
