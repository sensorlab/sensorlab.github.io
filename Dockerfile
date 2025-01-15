FROM ubuntu:24.04

# Meta labels
LABEL maintainer="Gregor Cerar <gregor.cerar@ijs.si>"

ARG UNAME=builder
ARG UID=1000
ARG GID=1000

# Suppress any manual intervention, while configuring packets
ARG DEBIAN_FRONTEND=noninteractive

# Hugo version
ARG HUGO=0.140.2

# Speedup Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Make RUN commands use `bash --login`:
SHELL ["/bin/bash", "--login", "-exc"]

WORKDIR /src

RUN <<EOT
# Initial packages
apt-get update -q
apt-get install -qyy \
    -o APT::Install-Recommends=false \
    -o APT::Install-Suggests=false \
    curl ca-certificates gdebi gnupg2 build-essential make git rsync python3-pip

# Download NodeJS
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt-get update -q
apt-get install -qyy \
    -o APT::Install-Recommends=false \
    -o APT::Install-Suggests=false \
    nodejs

# Install Hugo static site generator
curl -o hugo.deb -L https://github.com/gohugoio/hugo/releases/download/v${HUGO}/hugo_extended_${HUGO}_linux-amd64.deb
gdebi --non-interactive hugo.deb 
rm hugo.deb

# Cleanup
apt-get clean
rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Ensure user and group exists
groupadd --non-unique -g ${GID} -o ${UNAME}
useradd -m --uid ${UID} --gid ${GID} -o -s /bin/bash ${UNAME}
chown -R ${UID}:${GID} /src

EOT


USER ${UID}:${GID}

ENV PATH="${PATH}:/home/${UNAME}/.local/bin"

RUN <<EOT
python3 -m pip install \
    --user \
    --no-cache-dir \
    --break-system-packages \
    "arxiv~=2.1.0" \
    requests \
    unidecode \
    ujson
EOT
