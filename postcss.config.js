
const cssnano = require('cssnano')({ preset: 'default' });
const purgecss = require('@fullhuman/postcss-purgecss')({
  content: [
    './layouts/**/*.html',
    './static/scripts/*.js',
  ],
  whitelist: [
    'highlight',
    'language-bash',
    'pre',
    'video',
    'code',
    'content',
    'h3',
    'h4',
    'ul',
    'li'
  ]
});


module.exports = {
  plugins: [
    //require('postcss-import'),
    require('postcss-preset-env'),
    require('autoprefixer'),
    ...(process.env.HUGO_ENVIRONMENT === 'production'
        ? [purgecss, cssnano]
        : []
    )
  ]
};
