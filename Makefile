highlight:
	hugo gen chromastyles --style=monokai > assets/styles/_highlight.scss


prod:
	hugo server -v --gc --minify --disableFastRender

dev:
#	hugo server -v --gc --disableFastRender --navigateToChanged --buildDrafts --buildFuture
	hugo server -v --gc --disableFastRender --buildDrafts --buildFuture


build:
	hugo -v --gc --minify
