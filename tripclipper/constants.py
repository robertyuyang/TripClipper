VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".m4v",
    ".avi",
    ".mkv",
    ".webm",
    ".mts",
    ".m2ts",
}

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".heic",
    ".heif",
    ".webp",
    ".tif",
    ".tiff",
}

AUDIO_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".m4a",
    ".aac",
    ".flac",
    ".ogg",
    ".opus",
}

MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | IMAGE_EXTENSIONS | AUDIO_EXTENSIONS

SUBJECT_TYPES = {
    "landscape",
    "people",
    "people_landscape",
    "food",
    "building",
    "activity",
    "object",
    "other",
}

PEOPLE_PRESENCE = {"none", "single", "multiple", "small_group", "crowd"}

SHOT_SCALES = {
    "extreme_wide",
    "wide",
    "full",
    "medium",
    "close_up",
    "extreme_close_up",
}

SHOT_FUNCTIONS = {
    "establishing",
    "highlight",
    "transition",
    "detail",
    "reaction",
    "dialogue",
    "b_roll",
    "other",
}

SIMILAR_SELECTIONS = {"primary", "alternate", "rejected", "needs_review", "none"}

EDIT_CANDIDATE_STATUSES = {
    "default_selected",
    "alternate",
    "excluded",
    "needs_review",
}

SUBJECT_TYPE_LABELS = {
    "landscape": "风景",
    "people": "人物",
    "people_landscape": "人物加风景",
    "food": "食物",
    "building": "建筑",
    "activity": "活动现场",
    "object": "物件",
    "other": "其他",
}

PEOPLE_PRESENCE_LABELS = {
    "none": "无人",
    "single": "单人",
    "multiple": "多人",
    "small_group": "小群体",
    "crowd": "人群",
}

SHOT_SCALE_LABELS = {
    "extreme_wide": "大远景",
    "wide": "远景",
    "full": "全景",
    "medium": "中景",
    "close_up": "近景",
    "extreme_close_up": "大特写",
}

SHOT_FUNCTION_LABELS = {
    "establishing": "环境建立",
    "highlight": "高光",
    "transition": "转场",
    "detail": "细节",
    "reaction": "反应",
    "dialogue": "对白",
    "b_roll": "B-roll",
    "other": "其他",
}

SIMILAR_SELECTION_LABELS = {
    "primary": "雷同组主选",
    "alternate": "雷同组备选",
    "rejected": "雷同组不推荐",
    "needs_review": "待人工确认",
    "none": "无雷同组",
}

EDIT_CANDIDATE_LABELS = {
    "default_selected": "默认候选",
    "alternate": "备选候选",
    "excluded": "排除默认候选",
    "needs_review": "待人工确认",
}
