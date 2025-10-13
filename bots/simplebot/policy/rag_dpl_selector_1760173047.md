# 打招呼
UserUtter:你好
thought:用户打招呼，我应该回复用户
Selector:BotUtter


# 复杂查天气
UserUtter:成都和重庆天气咋样哪个好，我要看下去哪个城市旅游
thought:用户询问天气，同时问了成都和重庆天气，并让我做比较，我应该先执行Weather的到成都的天气，然后再执行Weather的到重庆的天气，然后比较
Selector:Weather


# 复杂查天气
UserUtter:成都和重庆天气咋样哪个好，我要看下去哪个城市旅游
Weather:<text>
thought:通过执行Weather拿到了成都的天气结果，此时还应该查询重庆的天气
Selector:Weather


# 复杂查天气
UserUtter:成都和重庆天气咋样哪个好，我要看下去哪个城市旅游
Weather:<text>
Weather:<text>
thought:通过执行Weather拿到了天气的结果，应该告诉用户
Selector:BotUtter


