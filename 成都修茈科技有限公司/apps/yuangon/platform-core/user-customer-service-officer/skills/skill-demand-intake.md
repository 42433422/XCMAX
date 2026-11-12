# skill-demand-intake

根据管理员提供的业务背景（brief），生成面向客户的需求询问话术，并附带需求提交表单链接（默认 `https://xiu-ci.com/market/about`）。

输出 JSON：`{ message_text, form_url, questions[] }`。
