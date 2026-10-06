# QueryBook UFCS-FQL Lab with everything included (PHP, ffmpeg, zstd).
#   docker compose up        then open http://127.0.0.1:8091
FROM php:8.3-cli-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg zstd libpng-dev libjpeg62-turbo-dev libwebp-dev libfreetype6-dev \
 && docker-php-ext-configure gd --with-jpeg --with-webp --with-freetype \
 && docker-php-ext-install -j"$(nproc)" gd pcntl \
 && docker-php-ext-enable opcache \
 && apt-get purge -y libpng-dev libjpeg62-turbo-dev libwebp-dev libfreetype6-dev \
 && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /lab
COPY . /lab
RUN php bin/doctor.php

EXPOSE 8091 9100 9101 9102 1935
CMD ["php", "-d", "upload_max_filesize=256M", "-d", "post_max_size=256M", "-S", "0.0.0.0:8091", "-t", "web"]
