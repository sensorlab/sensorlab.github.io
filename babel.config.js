module.exports = {
  presets: [
    [require('@babel/preset-env'), {
      modules: false,
      useBuiltIns: 'usage',
      corejs: 3,
    }],
  ]
};
