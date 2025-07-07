FROM debian:bookworm
ARG USER_NAME
ENV USER_NAME=${USER_NAME:-root}
ARG USER_ID
ENV USER_ID=${USER_ID:-0}

ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8

# Install deps for building securedrop-admin package
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get -y update && \
    apt-get -y upgrade && \
    apt-get -y install \
    coreutils \
    debhelper \
    devscripts \
    dh-python \
    make \
    pkg-config \
    python3-all \
    python3-pip \
    python3-setuptools \
    python3-venv \
    rsync \
    sudo \
    tzdata \
    unzip \
    virtualenv \
    gnupg2 \
    git

# Add user if necessary
RUN if test $USER_NAME != root ; then \
        useradd --no-create-home --home-dir /tmp --uid $USER_ID $USER_NAME && \
        echo "$USER_NAME ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers ; \
    fi

WORKDIR /src
COPY . /src

# Build and install the securedrop-admin package
RUN ln -s /src/builder/fixup-changelog.sh /fixup-changelog
RUN /src/builder/build-debs-admin.sh
RUN apt-get install -y /src/build/bookworm/securedrop-admin_*+bookworm_amd64.deb

# Install extra dev dependencies
RUN /usr/share/securedrop-admin/venv/bin/pip install --no-deps --require-hashes -r /src/admin/requirements-dev.txt

WORKDIR /src/admin

RUN chown -R $USER_NAME /src
