## 快捷创建智能体

cota提供了多个场景的智能体示例，方便测试和参考

```bash
cota init
```

执行上面初始化命令后，得到cota_projects目录
```
cota_projects
├── simplebot
│   ├── agent.yml
│   └── endpoints.yml
└── taskbot
    ├── agent.yml
    ├── endpoints.yml
    └── task.yml
```
cota_projects中的每个目录都是一个智能体，上面的示例中，simplebot 和 taskbot是两个agent实例，分别代表了简单的问答agent和任务执行agent。

## 文件说明

每个智能体至少包括`endpoints.yml`和`agent.yml`两个配置，对于任务类型的智能体还需包括`task.yml`。

`endpoints.yml` 定义agent运行需要的服务配置，包括服务的数据库类型及配置（用于维护对话状态）、通道的类型及配置、大语言模型的配置等。

```yml
base_store:
      type: Memory
      #dialect: mysql+pymysql  # the dialect used to interact with the db
      #host: localhost
      #port: 3306
      #db: mysql  # path to your db
      #username: root # username used for authentication
      #password: 12345678 # password used for authentication

channel:
      type: Memory
      #type: redis
      #host: localhost # Redis server host
      #port: 6379 # Redis server port
      #db: redis # Redis database number
      #password: your_redis_password # Redis password, if any

llm:
      type: openai
      #model: your_llm_model # openai, deepseek-chat, qwen 
      key: your_model_key
      apibase: your_model_api_base
```

`agent.yml` 定义了agent的基本元素，包括agent的`description`、`actions`、`dialogue`。其中 `description`是对该智能体的描述，
`actions`是智能体包含的动作的配置，`dialogue`代表整个对话流程的配置。

```yml
system:
  description: 你是一名电商导购助力，帮用户挑选合适的商品。你认真、专业、耐心的解决用户在购物中遇到的问题。

actions:
  Response:
    description: "回复用户的简单问题，回应用户打招呼、感谢、抱怨，引导用户"
    prompt: |
      根据任务描述和历史对话，生成回答。

      任务描述:
      {{task_description}}

      历史对话:
      {{history_messages}}

      请回答用户

  Selector:
    description: "选择合适的Actions"
    prompt: |
      根据历史对话，结合Action的描述，从Action列表中，选择最合适的Action。

      Action列表:
      {{bot_action_names_for_selector}}

      Action描述为:
      {{bot_action_descriptions_for_selector}}

      历史对话为:
      {{history_messages}}

      用户最后的对话为:
      {{latest_user_query}}

      请结合历史对话，和用户最后的对话，选择合适的Action

      输出格式为: <Action>

  GoodsRecommend:
    description: "当用户有对商品的需求时，结合用户的需求，推荐合适的商品"
    prompt: |      
      当前正在执行{{current_form_name}}, 其描述为{{current_form_description}}，请将结果{{current_form_execute_result}}返回。

    slots:
      keywords:
        description: 收集用户要购买的商品，及对商品的详细描述
        prompt: |
          当前正在执行Action {{current_form_name}}, 其描述为 {{current_form_description}}。

          根据历史对话：
          {{history_messages}}

          接下来需要询问用户，引导用户并收集用户挑选商品的需求。

          输出: <询问用户，并引导用户关于商品的细节描述>

    updater:
      description: "更新状态"
      prompt: |
        当前正在执行{{current_form_name}}， 其描述为{{current_form_description}}。根据对话内容，结合当前slot的状态，填充或重置slot的值。

        历史对话为:
        {{current_form_messages}}

        当前slots为:
        {{current_form_slot_states}}

        slots的含义为:
        {{current_form_slot_descriptions}}

        注意：
        1. 根据历史对话判断，当用户的需求较为简单，如只是简单的商品名称，没有详细的描述时，请不要填充slot的值
        2. 当用户需求足够清晰时，至少包含3项关于商品的详细描述，才填充slot的值，填充的值要包含商品及对商品的详细描述，以方便给用户精准的推荐商品
        3. 当用户拒绝进一步提供详细的描述的时候，请立刻填充slot的值，以进行下一步流程

        请填充slot的值，保持slots格式输出json字符串。

    executer:
      url: http://rap2api.taobao.org/app/mock/319677/goods/recommend
      methold: GET

dialogue:
  mode: agent
  max_bot_step: 20
  use_proxy_user: false
  max_proxy_user_step: 20
  use_proxy_user_breaker: true
  max_tokens: 500
```

更详细的配置说明和配置指引，会在下一章节详细介绍。


## 运行智能体

选择cota_projects中的文件夹进入 如simplebot

```
cd simplebot
```

补齐`endpoint.yml`的配置。

如果仅尝试，建议store和channel的类型都选择Memory，只需补齐LLM的配置即可运行。
`cota shell`方便通过命令行与智能体进行交互，适用于调试和验证agent。
```bash
cota shell
```

如果需要将cota部署到线上提供服务，需要运行
```bash
cota run
```
