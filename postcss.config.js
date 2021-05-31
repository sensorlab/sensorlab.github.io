
const cssnano = require('cssnano')({ preset: 'default' });
const purgecss = require('@fullhuman/postcss-purgecss')({
  content: [ './hugo_stats.json' ],
  defaultExtractor: (content) => {
      let els = JSON.parse(content).htmlElements;
      return els.tags.concat(els.classes, els.ids);
  }
});


module.exports = {
  plugins: [
    require('postcss-import'),
    //require('postcss-nested'),
    require('postcss-preset-env'),
    ...(process.env.HUGO_ENVIRONMENT === 'production'
        ? [purgecss, cssnano]
        : []
    )
  ]
};
