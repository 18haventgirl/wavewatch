export default {
  projectName: 'guanlan', date: '2026-11-20', designWidth: 750,
  deviceRatio: {640: 1.17, 750: 1, 828: 0.905},
  sourceRoot: 'src', outputRoot: 'dist', framework: 'react', compiler: 'webpack5',
  plugins: ['@tarojs/plugin-framework-react', '@tarojs/plugin-platform-weapp'],
  defineConstants: {API_BASE_URL: JSON.stringify(process.env.TARO_APP_API_BASE || 'http://127.0.0.1:8842')},
  mini: {postcss: {pxtransform: {enable: true}, url: {enable: true, config: {limit: 1024}}, cssModules: {enable: false}}}
}
