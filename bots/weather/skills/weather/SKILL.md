---
name: weather
description: 查询城市当前天气与未来16天内的逐日预报，提供温度、晴雨和降雨概率，支持明天、周末及多城市比较。
---

# 天气查询

## 确认地点与日期

从用户当前请求和对话中确认城市、日期。沿用已明确的信息；缺城市时只问城市，地名有歧义时确认省市，不重复询问。用户取消或换城市后按最新需求处理。

“现在”使用 current；“今天、明天、周末、某月某日”使用对应日期的 daily 预报。需要出行建议时，今日实况不代表全天。用户只问预报时不额外汇报当前天气。

## 查询

使用 `web_fetch` 的 GET 请求，读取返回的 JSON。每次请求设置 `timeout_seconds: 15`；非成功状态、错误字段、缺失目标数据不能当作有效天气。无需 Shell 或新工具。

1. 查地点：
   `https://geocoding-api.open-meteo.com/v1/search?name={city}&count=5&language=zh&format=json`
   城市名须 URL 编码。按 name、country、admin1 核对地点，使用返回的 latitude / longitude，不凭记忆编坐标。中文无匹配时可用同一地名的拼音或英文重试一次，例如杭州用 Hangzhou；依然无匹配时请用户补充地点。确有同名歧义时询问用户，不随意挑选。
2. 查当前天气：
   `https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code&timezone=auto`
   按 current_units 读取 current 的数值与 time。Open-Meteo 当前天气是模型数据，不称为某气象站的实测值。
3. 查今日或未来天气：
   `https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max&forecast_days=16&timezone=auto`
   daily.time 是目标城市当地日期数组，从当地今天起。以该数组首日为当地今天确定“明天”等相对日期，不能用模型记忆中的日期。周末一般指即将到来的周六、周日；查询发生在周末时包含当日及剩余周末，回复中写明具体日期；用户有不同日期要求时以用户为准，确实不清楚再确认。按相同数组下标取天气、最高/最低温、最大降雨概率，单位看 daily_units。需要实况和预报时可在同一次请求中合并 current 与 daily 参数。
4. 天气代码（WMO）：0 晴，1 大部晴朗，2 多云，3 阴，45/48 雾；51/53/55 毛毛雨，56/57 冻毛毛雨；61/63/65 雨，66/67 冻雨；71/73/75 雪，77 雪粒；80/81/82 阵雨，85/86 阵雪；95 雷暴，96/99 雷暴伴冰雹。缺代码或未知代码就省略天气描述；概率为 0 是有效值，null 是缺失，不能混淆。概率表示预报可能性，不保证一定下雨或不下雨。
5. 备用来源：Open-Meteo 无有效数据时，可查询一次
   `https://wttr.in/{city}?format=j1`。校验 nearest_area；实况读 current_condition[0]（temp_C / FeelsLikeC / weatherDesc / localObsDateTime）。预报只读 weather 中 date 与目标日期一致的项（mintempC / maxtempC / hourly 天气与降雨概率），不得用 current_condition 冒充预报，不能把 wttr 的单时段概率叫作全天概率。备用返回不含所需日期时，不继续无目的重试。

## 回复

先回答用户的问题，例如“上海明天有阵雨可能，出门带把伞更稳妥”，再给实际查到的温度、概率与具体日期。建议必须得到结果支持，不能根据未知天气推断晴雨。结尾可用一行简短标注来源和数据时间/预报日期，无须罗列每个字段、接口步骤或长段免责声明。

查询不到时简短说明本次没查到，可继续提供不依赖天气的帮助。目标日期超过返回的预报范围时说明暂时查不到那一天；不要泛称“我不能查未来天气”。多城市分别取对应数据；缺一个城市就不能完成可靠比较。
