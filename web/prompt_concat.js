// Comfyui_MKnode —— MK-提示词拼接 前端
//
// 动态输入端管理：连满当前输入端后自动补一个空槽，最多 10 个；
// 折叠末尾多余空槽，并始终保留一个空槽方便继续连接。
//
// 后端 nodes/prompt_concat.py 只在 schema 里声明了「提示词_01」，
// 其余由这里 addInput 添加。未声明但以「连线」形式传入的输入，ComfyUI 的
// execution.py 不做声明校验，仍会作为 kwargs 进入 concat。
//
// 注意：分隔符是个 widget，它同样会出现在 node.inputs 里（实测位置在
// 提示词_01 之后）。所以下面一律按名字前缀过滤，绝不假设下标。
//
// 命名隔离：扩展名带包前缀，避免与源包 Comfyui-MK_Tools 的同名扩展互相覆盖。

import { app } from "../../scripts/app.js";

const NODE_NAME = "MK_PromptConcat";
const INPUT_PREFIX = "提示词_";
const MAX_INPUTS = 10; // 与 nodes/prompt_concat.py 的 MAX_PROMPT_INPUTS 保持一致
const MIN_INPUTS = 2; // 至少保留 2 个输入端，始终留一个空槽

const inputName = (index) => `${INPUT_PREFIX}${String(index).padStart(2, "0")}`;

app.registerExtension({
    name: "Comfyui_MKnode.PromptConcat",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        // this.inputs 在极端时机可能为空，统一走这里取
        const promptInputsOf = (node) =>
            (node.inputs || []).filter((i) => i.name && i.name.startsWith(INPUT_PREFIX));

        // 取当前已用序号的最大值，避免出现重名输入
        const maxIndexOf = (node) => {
            let max = 0;
            for (const inp of promptInputsOf(node)) {
                const n = parseInt(inp.name.slice(INPUT_PREFIX.length), 10);
                if (Number.isFinite(n) && n > max) max = n;
            }
            return max;
        };

        // 在末尾补 num 个空输入，不越过上限
        nodeType.prototype.addPromptInput = function (num = 1) {
            for (let i = 0; i < num; i++) {
                const next = maxIndexOf(this) + 1;
                if (next > MAX_INPUTS) break;
                this.addInput(inputName(next), "STRING");
            }
        };

        // 收敛输入端：折叠末尾多余空槽，保证末尾留一个空槽，且不少于 MIN_INPUTS 个
        nodeType.prototype.stabilize = function () {
            const inputs = promptInputsOf(this);

            // 末尾未连接的空槽只保留一个
            while (inputs.length > MIN_INPUTS && !inputs[inputs.length - 1].link) {
                const slot = this.inputs.indexOf(inputs.pop());
                if (slot < 0) break;
                this.removeInput(slot);
            }

            const last = inputs[inputs.length - 1];
            if (last && last.link && inputs.length < MAX_INPUTS) {
                // 最后一个输入已连接且未到上限 → 再补一个空槽
                this.addPromptInput(1);
            } else if (inputs.length < MIN_INPUTS) {
                // 退化情形：输入端被删空（旧存档 / 手工改过 JSON）→ 补齐，避免节点卡死
                this.addPromptInput(MIN_INPUTS - inputs.length);
            }
        };

        // 连线变化可能连续触发，防抖后统一收敛
        nodeType.prototype.scheduleStabilize = function (ms = 64) {
            clearTimeout(this._mkPromptStabilizeTimer);
            this._mkPromptStabilizeTimer = setTimeout(() => this.stabilize(), ms);
        };

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            // 初始补一个空槽（提示词_01 已由 INPUT_TYPES 声明）
            this.addPromptInput(1);
            return result;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = onConfigure?.apply(this, arguments);
            // 加载工作流后补一次：兼容末尾没留空槽、甚至输入被删空的旧存档
            this.scheduleStabilize();
            return result;
        };

        const onConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            const result = onConnectionsChange?.apply(this, arguments);
            this.scheduleStabilize();
            return result;
        };
    },
});
