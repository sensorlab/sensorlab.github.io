FROM klakegg/hugo:0.91.2-ext-alpine

WORKDIR /src

COPY . /src

CMD bash -c "npm install && hugo"
