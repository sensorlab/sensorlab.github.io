# Borrowed from: https://gist.github.com/mpneuried/0594963ad38e68917ef189b4e6a269db
PORT ?= 1313
BASE_URL ?= https://sensorlab.ijs.si/

HUGO_DEV_SERVER_ARGS=-v --gc --disableFastRender --buildDrafts --buildFuture
HUGO_PROD_SERVER_ARGS=-v --gc --minify --disableFastRender --environment production

HUGO_PROD_BUILD_ARGS=-v --gc --minify --baseURL=$(BASE_URL)

# HELP
# This will output the help for each task
# thanks to https://marmelab.com/blog/2016/02/29/auto-documented-makefile.html
.PHONY: help

help: ## This help.
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.DEFAULT_GOAL := help

#highlight:
#	hugo gen chromastyles --style=monokai > assets/styles/_highlight.scss

clean:
	rm -rf node_modules resources hugo_stats.json .hugo_build.lock

public: clean ## build ./public folder with static content for serving
	# Update COBISS entries with python script
	python3 scripts/cobiss_parser.py

	# Get NodeJS dependencies
	npm ci 

	# Let HUGO build static content
	hugo $(HUGO_PROD_BUILD_ARGS)


prepare-deploy: clean
	# Update COBISS entries with python script
	python3 scripts/cobiss_parser.py

	# Get NodeJS dependencies
	npm ci 

	# Let HUGO build static content
	hugo $(HUGO_PROD_BUILD_ARGS) -d ./public.tmp

deploy: prepare-deploy 
	# Cleanup previous public folder, replace content with new build
	rsync -avh --delete ./public.tmp/ ./public/

	make clean


hugo-dev-server:
	hugo server $(HUGO_DEV_SERVER_ARGS)

hugo-demo-server:
	hugo server $(HUGO_PROD_SERVER_ARGS)

container:
	docker build \
		--build-arg UID=$(shell id -u) \
		--build-arg GID=$(shell id -g) \
		-t sensorlab/hugo \
		.

build: container ## produce public folder with content in container
	docker run \
		--rm \
		-v $(shell pwd):/src \
		--name hugo-builder \
		sensorlab/hugo \
		make public

run: container ## Run Hugo in container with development mode
	docker run \
		-i -t \
		--rm \
		-v $(shell pwd):/src \
		-p=$(PORT):1313 \
		--name hugo-builder \
		sensorlab/hugo \
		hugo server $(HUGO_DEV_SERVER_ARGS) --bind 0.0.0.0

dev: run ## Run Hugo in container with development mode

shell: container ## Run shell inside container
	docker run \
		-i -t \
		--rm \
		-v $(shell pwd):/src \
		-p=$(PORT):1313 \
		--name hugo-builder \
		sensorlab/hugo \
		bash
