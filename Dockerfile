FROM klakegg/hugo:0.90.0-ext-alpine

WORKDIR /src

COPY . /src

CMD bash -c "npm install && hugo"
