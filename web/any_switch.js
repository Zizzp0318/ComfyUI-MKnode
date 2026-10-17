// Comfyui_MKnode —— MK-任意切换 前端
//
// 迁移自 rgthree-comfy 的 src_web/comfyui/any_switch.ts。
//
// 负责两件事：
// 1. 动态输入端：连满当前输入后自动补一个空槽，末尾多余空槽折叠，至少保留 MIN_INPUTS 个；
// 2. 类型跟随：输出槽与所有输入槽的类型跟着「上游接进来的线」走。
//    槽位类型是 `*` 时，顺着连线一路找到第一个具体类型，全节点就统一成它，
//    这样接 IMAGE 就显示图像色、接 MODEL 就显示模型色，不会一直是灰的未知类型。
//
// 后端 nodes/any_switch.py 的 INPUT_TYPES 里没有声明 any_NN，
// 它们全靠这里 addInput 添加；V1 的 execution.py 对「连线型输入」不做声明校验，
// 未声明的输入仍会作为 kwargs 传进 switch()。
//
// Nodes 2.0 兼容：这里只用图结构（node.inputs / graph.links）与生命周期钩子，
// 不碰任何 canvas 绘制钩子（onDrawBackground / onMouseDown / graph_mouse 等）。
//
// 命名隔离：扩展名带包前缀，避免与 rgthree 的同名扩展互相覆盖。

import { app } from "../../scripts/app.js";

const NODE_TYPE = "MK_AnySwitch";
const INPUT_PREFIX = "any_";
const MIN_INPUTS = 5; // 与 nodes/any_switch.py 的 MIN_INPUTS 保持一致
const MAX_INPUTS = 64; // 与 nodes/any_switch.py 的 MAX_INPUTS 保持一致

const ANY_TYPE = "*";

// 顺着连线找类型的最大跳数，防止节点成环时无限递归
const MAX_DEPTH = 32;

const inputName = (index) => `${INPUT_PREFIX}${String(index).padStart(2, "0")}`;

/** 取槽位上的连线对象；不同 LiteGraph 版本既可能给 id，也可能给对象本身 */
const linkOf = (graph, slot) => {
    const link = slot?.link;
    if (link == null) return null;
    if (typeof link === "object") return link;
    return graph?.links?.[link] ?? null;
};

/**
 * 顺着连线找「另一头」的槽位。
 * @param node 当前节点
 * @param dir  "in" 表示从本节点输入往上游找，"out" 表示从本节点输出往下游找
 * @param index 槽位下标
 * @returns {{node: object, index: number}|null}
 */
const linkedSlot = (node, dir, index) => {
    const graph = app.graph || app.canvas?.graph;
    if (!graph) return null;
    const slot = (dir === "in" ? node.inputs : node.outputs)?.[index];
    if (!slot) return null;

    if (dir === "in") {
        const link = linkOf(graph, slot);
        if (!link) return null;
        const origin = graph.getNodeById?.(link.origin_id);
        return origin ? { node: origin, index: link.origin_slot } : null;
    }

    // 输出可能接了很多条线，取第一条能找到的
    const links = Array.isArray(slot.links) ? slot.links : [];
    for (const id of links) {
        const link = typeof id === "object" ? id : graph.links?.[id];
        if (!link) continue;
        const target = graph.getNodeById?.(link.target_id);
        if (target) return { node: target, index: link.target_slot };
    }
    return null;
};

/** 读一个槽位自身的类型；`*` 或非字符串一律算「未知」 */
const slotType = (node, dir, index) => {
    const slot = (dir === "in" ? node.inputs : node.outputs)?.[index];
    const type = slot?.type;
    return typeof type === "string" && type && type !== ANY_TYPE ? type : null;
};

/**
 * 某节点的输出槽最终代表什么类型。
 * 输出是 `*`（例如上游又是一个任意切换）时，它的类型由该节点自己的输入决定，
 * 所以这里继续往它的上游追。
 */
const typeOfOutput = (node, index, depth) => {
    const own = slotType(node, "out", index);
    if (own) return own;
    if (depth > MAX_DEPTH) return null;
    const inputs = node.inputs || [];
    for (let i = 0; i < inputs.length; i++) {
        const found = typeUpstream(node, i, depth + 1);
        if (found) return found;
    }
    return null;
};

/** 从 node.inputs[index] 的连线往上游找类型 */
const typeUpstream = (node, index, depth) => {
    if (depth > MAX_DEPTH) return null;
    const other = linkedSlot(node, "in", index);
    if (!other) return null;
    return typeOfOutput(other.node, other.index, depth + 1);
};

/** 从 node.outputs[index] 的连线往下游找类型 */
const typeDownstream = (node, index, depth) => {
    if (depth > MAX_DEPTH) return null;
    const other = linkedSlot(node, "out", index);
    if (!other) return null;
    const own = slotType(other.node, "in", other.index);
    if (own) return own;
    // 对方输入也是 * → 继续往它的下游追
    const outputs = other.node.outputs || [];
    for (let i = 0; i < outputs.length; i++) {
        const found = typeDownstream(other.node, i, depth + 1);
        if (found) return found;
    }
    return null;
};

/**
 * 解析整个节点应该显示成什么类型：先看输入，再看输出。
 *
 * 注意：这里**只认别人的槽位类型**，绝不读本节点自己的槽位——本节点的槽位会被
 * applyAnyType 改写成具体类型，一旦回头读自己，就再也回不到 `*` 了
 * （断线后类型卡住不变正是这个原因）。
 */
const resolveNodeType = (node) => {
    const inputs = node.inputs || [];
    for (let i = 0; i < inputs.length; i++) {
        const found = typeUpstream(node, i, 0);
        if (found) return found;
    }
    const outputs = node.outputs || [];
    for (let i = 0; i < outputs.length; i++) {
        const found = typeDownstream(node, i, 0);
        if (found) return found;
    }
    return null;
};

app.registerExtension({
    name: "Comfyui_MKnode.AnySwitch",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE) return;

        /** 本节点的输入端（只认 any_ 前缀） */
        const anyInputsOf = (node) =>
            (node.inputs || []).filter((i) => i?.name && i.name.startsWith(INPUT_PREFIX));

        /** 已用序号的最大值，避免序号有缺口时补出重名输入 */
        const maxIndexOf = (node) => {
            let max = 0;
            for (const input of anyInputsOf(node)) {
                const n = parseInt(input.name.slice(INPUT_PREFIX.length), 10);
                if (Number.isFinite(n) && n > max) max = n;
            }
            return max;
        };

        /** 在末尾补 num 个空输入，不越过上限 */
        nodeType.prototype.addAnyInput = function (num = 1) {
            for (let i = 0; i < num; i++) {
                const next = maxIndexOf(this) + 1;
                if (next > MAX_INPUTS) break;
                const index = this.inputs?.length ?? 0;
                this.addInput(inputName(next), ANY_TYPE);
                const slot = this.inputs?.[index];
                if (slot) slot.label = `任意 ${String(next).padStart(2, "0")}`;
            }
        };

        /** 把输入/输出槽的类型统一成当前解析出来的类型 */
        nodeType.prototype.applyAnyType = function () {
            const type = resolveNodeType(this) || ANY_TYPE;

            for (const input of this.inputs || []) {
                if (input) input.type = type;
            }
            for (const output of this.outputs || []) {
                if (!output) continue;
                output.type = type;
                // 输出名回落到中文「任意」，解析出类型时直接显示类型名，便于确认接了什么东西
                output.label = type === ANY_TYPE ? "任意" : type;
            }

            // 类型变化后让前端重画连接点颜色（Nodes 1.0 与 2.0 都靠这个标记）
            if (this.graph) this.graph._version = (this.graph._version || 0) + 1;
            app.canvas?.setDirty?.(true, true);
        };

        /** 收敛输入端：折叠末尾多余空槽 → 保证下限 → 末尾已连接就再补一个 → 同步类型 */
        nodeType.prototype.stabilize = function () {
            const inputs = anyInputsOf(this);

            // 末尾未连接的空槽只保留到下限为止
            while (inputs.length > MIN_INPUTS && !inputs[inputs.length - 1].link) {
                const slot = this.inputs.indexOf(inputs.pop());
                if (slot < 0) break;
                this.removeInput(slot);
            }

            if (inputs.length < MIN_INPUTS) {
                // 退化情形：输入端被删空（旧存档 / 手工改过 JSON）→ 补齐，避免节点卡死
                this.addAnyInput(MIN_INPUTS - inputs.length);
            } else {
                const last = inputs[inputs.length - 1];
                // 最后一个空槽被连上 → 再补一个新空槽，方便继续接线
                if (last?.link && inputs.length < MAX_INPUTS) this.addAnyInput(1);
            }

            this.applyAnyType();
        };

        /** 连线变化可能连续触发，防抖后统一收敛 */
        nodeType.prototype.scheduleStabilize = function (ms = 64) {
            clearTimeout(this._mkAnySwitchTimer);
            this._mkAnySwitchTimer = setTimeout(() => this.stabilize(), ms);
        };

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            this.addAnyInput(this.inputs?.length ? 0 : MIN_INPUTS);
            this.applyAnyType();
            return result;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = onConfigure?.apply(this, arguments);
            // 加载工作流后补一次：兼容末尾没留空槽、输入被删空、类型没同步的旧存档
            this.scheduleStabilize();
            return result;
        };

        const onConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            const result = onConnectionsChange?.apply(this, arguments);
            this.scheduleStabilize();
            return result;
        };

        // 节点被删除时清掉未执行的防抖任务
        const onRemoved = nodeType.prototype.onRemoved;
        nodeType.prototype.onRemoved = function () {
            clearTimeout(this._mkAnySwitchTimer);
            const result = onRemoved?.apply(this, arguments);
            return result;
        };
    },
});
