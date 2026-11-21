export default defineAppConfig({
  pages: ['pages/feed/index','pages/digests/index','pages/messages/index','pages/profile/index','pages/login/index','pages/article/index'],
  window: {navigationBarTitleText: '观澜',navigationBarBackgroundColor:'#f5f7fb',navigationBarTextStyle:'black',backgroundColor:'#f5f7fb'},
  tabBar: {color:'#7d8799',selectedColor:'#1677ff',backgroundColor:'#ffffff',borderStyle:'white',list:[
    {pagePath:'pages/feed/index',text:'动态'}, {pagePath:'pages/digests/index',text:'日报'},
    {pagePath:'pages/messages/index',text:'消息'}, {pagePath:'pages/profile/index',text:'我的'}]}
})
