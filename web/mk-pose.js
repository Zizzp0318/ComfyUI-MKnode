import { defineGallery } from "./gallery-core.js";

defineGallery({
	extension: "ComfyUI.MKGallery.Pose",
	nodeName: "MKPosePicker",
	route: "mkposes",
	widgetName: "姿态",
	itemLabel: "姿态",
	unit: "个",
	domWidgetName: "mk_pose_gallery",
});
