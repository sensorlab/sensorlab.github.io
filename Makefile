# Borrowed from: https://gist.github.com/mpneuried/0594963ad38e68917ef189b4e6a269db
PORT ?= 1313
BASE_URL ?= https://sensorlab.ijs.si/

HUGO_DEV_SERVER_ARGS= --gc --disableFastRender --buildDrafts --buildFuture
HUGO_PROD_SERVER_ARGS= --gc --minify --disableFastRender

HUGO_PROD_BUILD_ARGS= --gc --minify --baseURL=$(BASE_URL) --environment ijs.si

# HELP
# This will output the help for each task
# thanks to https://marmelab.com/blog/2016/02/29/auto-documented-makefile.html
.PHONY: help clean cobiss public public.tmp

help: ## This help.
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.DEFAULT_GOAL := help

#highlight:
#	hugo gen chromastyles --style=monokai > assets/styles/_highlight.scss

clean:  # Clean output files and folders
	rm -rf ./node_modules ./resources ./hugo_stats.json ./.hugo_build.lock ./public.tmp


dev: container  ## Run Hugo in container with development mode
	docker run \
		-i -t \
		--rm \
		-v $(shell pwd):/src \
		-p=$(PORT):1313 \
		--name hugo-builder \
		sensorlab/hugo \
		hugo server $(HUGO_DEV_SERVER_ARGS) --bind 0.0.0.0


shell: container ## Run shell inside container
	docker run \
		-i -t \
		--rm \
		-v $(shell pwd):/src \
		-p=$(PORT):1313 \
		--name hugo-builder \
		sensorlab/hugo


cobiss:  ## Update COBISS entries with Python scripts
	python3 scripts/cobiss_parser.py


public:  ## build ./public folder with static content for serving
	# Get NodeJS dependencies
	npm ci
	npx browserslist@latest --update-db

	# Let HUGO build static content
	hugo $(HUGO_PROD_BUILD_ARGS)


public.tmp:  ## build ./public.tmp folder with static content for serving
	# Get NodeJS dependencies
	npm ci
	npx browserslist@latest --update-db

	# Let HUGO build static content
	hugo $(HUGO_PROD_BUILD_ARGS) -d ./public.tmp


build: container  ## produce public folder with content in container
	docker run \
		--rm \
		-v $(shell pwd):/src \
		-e HUGO_ENVIRONMENT=production \
		-e HUGO_ENV=production \
		-e NODE_ENV=production \
		-e BABEL_ENV=production \
		--name hugo-builder \
		sensorlab/hugo \
		bash -c "make clean && make cobiss && make public && make clean"


sync: ## Cleanup previous public folder, replace content with new build
	rsync -avh --delete ./public.tmp/ ./public/


deploy: container  ## produce public folder with content in container
	docker run \
		--rm \
		-v $(shell pwd):/src \
		--name hugo-builder \
		sensorlab/hugo \
		bash -c "make clean && make cobiss && make public.tmp && make sync && make clean"


container:
	docker build -t sensorlab/hugo .
