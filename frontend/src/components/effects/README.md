# Vue Bits Effects

这是为 `D:\Aiapi_test\frontend` 准备的 Vue Bits 效果组件文件包。

## 文件

```text
src/components/effects/
├── CardSwap.vue
├── DarkVeil.vue
├── SpecularButton.vue
└── StrokeText.vue
```

## 依赖

```bash
npm install gsap ogl
```

## 放置方式

将 `src/components/effects/` 目录复制到：

```text
D:\Aiapi_test\frontend\src\components\effects
```

然后即可：

```ts
import StrokeText from '@/components/effects/StrokeText.vue'
import DarkVeil from '@/components/effects/DarkVeil.vue'
import CardSwap from '@/components/effects/CardSwap.vue'
import SpecularButton from '@/components/effects/SpecularButton.vue'
```

## 注意

这些组件依赖 Tailwind CSS 中使用的 utility classes。

`CardSwap.vue` 同时导出了官方源码中的 `Card` helper：

```ts
import CardSwap, { Card } from '@/components/effects/CardSwap.vue'
```

当前文件包只负责提供 Vue Bits effects，不包含首页业务组件。
