import { defineGallery } from "./gallery-core.js";

defineGallery({
	extension: "ComfyUI.MKGallery.Face",
	nodeName: "MKFacePicker",
	route: "mkfaces",
	widgetName: "脸模",
	itemLabel: "脸模",
	unit: "张",
	domWidgetName: "mk_face_gallery",
});
