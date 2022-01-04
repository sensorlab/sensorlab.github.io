# Borrowed from: https://gist.github.com/mpneuried/0594963ad38e68917ef189b4e6a269db
APP_NAME=sensorlab.github.io
PORT=1313

HUGO_DEV_CMD=server -v --gc --disableFastRender --buildDrafts --buildFuture
HUGO_PROD_CMD=server -v --gc --minify --disableFastRender

#highlight:
#	hugo gen chromastyles --style=monokai > assets/styles/_highlight.scss


#prod:
#	hugo server -v --gc --minify --disableFastRender

#dev:
#	hugo server -v --gc --disableFastRender --navigateToChanged --buildDrafts --buildFuture
#	hugo server -v --gc --disableFastRender --buildDrafts --buildFuture


#build:
#	hugo -v --gc --minify


# HELP
# This will output the help for each task
# thanks to https://marmelab.com/blog/2016/02/29/auto-documented-makefile.html
.PHONY: help

help: ## This help.
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.DEFAULT_GOAL := help


build: ## Build the container
	docker build -t $(APP_NAME) .

build-nc: ## Build the container without cache
	docker build --no-cache -t $(APP_NAME) .

run: ## Run Hugo in container with development mode
	docker run -i -t --rm -v $(PWD):/src -p=$(PORT):1313 --name="$(APP_NAME)" $(APP_NAME) $(HUGO_DEV_CMD)

dev: run ## Run Hugo in container with development mode

prod: ## Run Hugo in container with production mode
	docker run -i -t --rm -v $(PWD):/src -p=$(PORT):1313 --name="$(APP_NAME)" $(APP_NAME) $(HUGO_PROD_CMD)

up: build run ## Run container on port configured

stop: ## Stop and remove a running container
	docker stop $(APP_NAME); docker rm $(APP_NAME)
