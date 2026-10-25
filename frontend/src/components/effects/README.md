# Vue Bits Effects

ApiPilot 前端的 Vue Bits 视觉效果组件，位于 `frontend/src/components/effects/`。

## 文件

~~~text
src/components/effects/
├── CardSwap.vue
├── DarkVeil.vue
├── SpecularButton.vue
└── StrokeText.vue
~~~

## 依赖

~~~bash
npm install gsap ogl
~~~

依赖由前端 `package.json` 管理；安装项目依赖后即可使用。

## 使用

~~~ts
import StrokeText from '@/components/effects/StrokeText.vue'
import DarkVeil from '@/components/effects/DarkVeil.vue'
import CardSwap from '@/components/effects/CardSwap.vue'
import SpecularButton from '@/components/effects/SpecularButton.vue'
~~~

## 注意

这些组件依赖 Tailwind CSS 中使用的 utility classes。

`CardSwap.vue` 同时导出了官方源码中的 `Card` helper：

~~~ts
import CardSwap, { Card } from '@/components/effects/CardSwap.vue'
~~~

当前目录只提供 Vue Bits effects，不包含首页业务组件。
