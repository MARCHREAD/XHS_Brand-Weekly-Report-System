from __future__ import annotations

import html
import re
from typing import Annotated, Any, Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


TagValue = Annotated[str, StringConstraints(min_length=1, max_length=64)]
TagList = Annotated[list[TagValue], Field(max_length=30)]

PgySortColumn = Literal[
    "comprehensiverank",
    "fansCount",
    "price",
    "clickNum",
    "mEngagementNum",
    "accumCommonImpMedinNum30d",
    "accumPicCommonImpMedinNum30d",
    "accumVideoCommonImpMedinNum30d",
    "pictureClickMidNum",
    "videoClickMidNum",
    "pictureInterMidNum",
    "videoInterMidNum",
    "thousandLikePercent30",
    "pictureThousandLikePercent30",
    "videoThousandLikePercent30",
    "hundredLikePercent30",
    "pictureHundredLikePercent30",
    "videoHundredLikePercent30",
    "videoFinishRate",
    "accumCoopImpMedinNum30d",
    "readMidCoop30",
    "interMidCoop30",
    "mCpuvNum30d",
    "picturePrice",
    "videoPrice",
    "pictureReadCost",
    "videoReadCost",
    "inviteReply48hNumRatio",
    "fans30GrowthRate",
    "fansActiveIn28dLv",
    "fansEngageNum30dLv",
    "kliveCnt30d",
    "avgLiveViewerNum",
    "avgAgmv90d",
]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NumericRange(StrictRequest):
    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> "NumericRange":
        if self.min is None and self.max is None:
            raise ValueError("range requires min or max")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("range min must be less than or equal to max")
        return self

    def upstream(self, *, percent: bool = False) -> list[float]:
        lower = 0.0 if self.min is None else self.min
        upper = -1.0 if self.max is None else self.max
        if percent:
            lower /= 100
            if upper != -1:
                upper /= 100
        return [lower, upper]


def parse_note_link(value: str) -> tuple[str, str, str]:
    text = html.unescape(value).strip().strip("'\"‘’“”")
    url_match = re.search(r"https?://[^\s]+", text)
    if url_match:
        text = url_match.group(0).rstrip(".,;，；")
    elif text.startswith("www."):
        text = "https://" + text
    parsed = urlsplit(text)
    query = parse_qs(parsed.query, keep_blank_values=True)
    note_match = re.search(r"(?<![0-9a-f])[0-9a-f]{24}(?![0-9a-f])", parsed.path, re.IGNORECASE)
    note_id = str(
        (note_match.group(0) if note_match else "")
        or (query.get("note_id") or query.get("noteId") or [""])[0]
    )
    xsec_token = str((query.get("xsec_token") or query.get("xsecToken") or [""])[0])
    xsec_source = str((query.get("xsec_source") or query.get("xsecSource") or [""])[0])
    missing = [
        name
        for name, field in (
            ("note_id", note_id),
            ("xsec_token", xsec_token),
            ("xsec_source", xsec_source),
        )
        if not field
    ]
    if missing:
        raise ValueError("note URL is missing required fields: " + ", ".join(missing))
    return note_id, xsec_token, xsec_source


class PgyNoteDetailRequest(StrictRequest):
    note_url: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_note_url(self) -> "PgyNoteDetailRequest":
        self.parameters()
        return self

    def parameters(self) -> tuple[str, str, str]:
        return parse_note_link(self.note_url)


class PgyBloggerDetailRequest(StrictRequest):
    user_id: str = Field(min_length=1, max_length=64)
    business: Literal[0, 1] = Field(default=0, description="笔记口径：0=日常笔记，1=合作笔记")
    increase_type: Literal[1, 2] = Field(default=1, description="粉丝曲线：1=粉丝总量，2=每日新增")
    date_type: Literal[1, 2] = Field(default=1, description="粉丝曲线范围：1=近30日，2=近60日")


class PgySimilarBloggerRequest(StrictRequest):
    user_id: str = Field(min_length=1, max_length=64)
    pages: int = Field(default=1, ge=1, le=250, description="从起始页连续抓取的页数")
    page_num: int = Field(default=1, ge=1, le=250, description="兼容字段：起始页，从 1 开始")
    page_size: int = Field(default=4, ge=1, le=4, description="每页数量，蒲公英最多返回 4 条")

    @model_validator(mode="after")
    def validate_page_range(self) -> "PgySimilarBloggerRequest":
        if self.page_num + self.pages - 1 > 250:
            raise ValueError("page range cannot exceed page 250")
        return self


class GoalFilters(StrictRequest):
    market_target: dict[str, Any] | str | None = None


class BloggerFilters(StrictRequest):
    content_tag: TagList = Field(default_factory=list)
    personal_tags: TagList = Field(default_factory=list)
    feature_tags: TagList = Field(default_factory=list)
    content_theme: TagList = Field(default_factory=list)
    audience20: TagList = Field(default_factory=list)
    note_scene: TagList = Field(default_factory=list)
    consumer_behavior: TagList = Field(default_factory=list)
    industry_crowd: TagList = Field(default_factory=list)
    gender: Literal["男", "女"] | None = None
    location: TagList = Field(default_factory=list)
    signed: Literal[-1, 0, 1] | None = None


class FansFilters(StrictRequest):
    count: NumericRange | None = None
    age: Literal[0, 1, 2, 3, 4, 5] | None = None
    gender: Literal[0, 1, 2] | None = None
    location: TagList = Field(default_factory=list)
    marital_status: Literal[-1, 0, 1] | None = None
    consumption_level: Literal[-1, 0, 1, 2] | None = None
    child_age: list[Literal[0, 2, 3, 4, 5, 6, 7, 8]] = Field(default_factory=list, max_length=30)
    device_price: list[
        Literal[
            "0-999",
            "1000-1999",
            "2000-2999",
            "3000-3999",
            "4000-4999",
            "5000-5999",
            "6000-6999",
            "7000-7999",
            "8000+",
        ]
    ] = Field(default_factory=list, max_length=30)
    device_brand: list[
        Literal["苹果", "华为", "OPPO", "VIVO", "荣耀", "小米", "一加", "魅族", "中兴", "联想"]
    ] = Field(default_factory=list, max_length=30)


class NoteFilters(StrictRequest):
    imp_median: NumericRange | None = None
    read_median: NumericRange | None = None
    inter_median: NumericRange | None = None
    thousand_like_percent: NumericRange | None = None
    note_type: Literal[0, 1, 2] | None = None


class CoopFilters(StrictRequest):
    pic_price: NumericRange | None = None
    video_price: NumericRange | None = None
    order_count: NumericRange | None = None
    reply_48h_ratio: NumericRange | None = None
    industry: Literal[
        "不限",
        "美妆个护",
        "食品饮料",
        "母婴",
        "3c及电器",
        "日用百货",
        "服装配饰",
        "互联网",
        "生活服务",
        "家居建材",
        "汽车",
    ] | None = None
    brand_ids: TagList = Field(default_factory=list)
    exclude_brands: bool | None = None
    imp_median: NumericRange | None = None
    read_median: NumericRange | None = None
    inter_median: NumericRange | None = None
    cpuv: NumericRange | None = None
    estimate_cpuv: NumericRange | None = None
    pic_cpm: NumericRange | None = None
    video_cpm: NumericRange | None = None
    pic_read_price: NumericRange | None = None
    video_read_price: NumericRange | None = None
    pic_engage_cost: NumericRange | None = None
    video_engage_cost: NumericRange | None = None


class LiveFilters(StrictRequest):
    live_count: NumericRange | None = None
    avg_viewer: NumericRange | None = None
    avg_gmv: NumericRange | None = None


class FlagFilters(StrictRequest):
    is_star: bool | None = None
    high_quality: bool | None = None
    new_high_quality: bool | None = None
    note_and_live: bool | None = None
    filter_intention: bool | None = None
    industry_first: TagValue | None = None
    industry_second: TagValue | None = None
    activity_codes: TagList = Field(default_factory=list)
    exclude_low_active: bool | None = None
    exclude_fans_down: bool | None = None
    exclude_cooperated: bool | None = None
    exclude_invited: bool | None = None

    @model_validator(mode="after")
    def validate_industry_pair(self) -> "FlagFilters":
        if self.industry_second and not self.industry_first:
            raise ValueError("industry_second requires industry_first")
        return self


class PgyBloggerSearchRequest(StrictRequest):
    keyword: str = Field(default="", max_length=100)
    search_type: Literal[0, 1] = Field(default=1, description="1=按笔记关键词找博主，0=按昵称搜索")
    column: PgySortColumn = Field(default="comprehensiverank", description="排序字段")
    sort: Literal["desc", "asc"] = Field(default="desc", description="desc=降序，asc=升序")
    brand_user_id: str | None = Field(default=None, max_length=64)
    similar_user_id: str | None = Field(default=None, max_length=64)
    similar_word: str | None = Field(default=None, max_length=100)
    track_id: str | None = Field(default=None, max_length=200, description="续页时复用的蒲公英 trackId")
    pages: int = Field(default=1, ge=1, le=250, description="从起始页连续抓取的页数")
    page_num: int = Field(default=1, ge=1, le=250, description="兼容字段：起始页，最多 250 页")
    page_size: int = Field(default=20, ge=1, le=20, description="每页数量，建议保持网页默认值 20")
    goal: GoalFilters = Field(default_factory=GoalFilters)
    blogger: BloggerFilters = Field(default_factory=BloggerFilters)
    fans: FansFilters = Field(default_factory=FansFilters)
    note: NoteFilters = Field(default_factory=NoteFilters)
    coop: CoopFilters = Field(default_factory=CoopFilters)
    live: LiveFilters = Field(default_factory=LiveFilters)
    flags: FlagFilters = Field(default_factory=FlagFilters)

    @model_validator(mode="after")
    def validate_page_range(self) -> "PgyBloggerSearchRequest":
        if self.page_num + self.pages - 1 > 250:
            raise ValueError("page range cannot exceed page 250")
        return self

    def to_upstream(self, *, fans_locations: list[str] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "searchType": self.search_type,
            "column": self.column,
            "sort": self.sort,
            "pageNum": self.page_num,
            "pageSize": self.page_size,
        }
        optional = {
            "keyword": self.keyword or None,
            "brandUserId": self.brand_user_id,
            "similarUserId": self.similar_user_id,
            "similarWord": self.similar_word,
            "marketTarget": self.goal.market_target,
            "contentTag": self.blogger.content_tag or None,
            "personalTags": self.blogger.personal_tags or None,
            "featureTags": self.blogger.feature_tags or None,
            "contentThemeLabel": self.blogger.content_theme or None,
            "top20CrowdsLabel": self.blogger.audience20 or None,
            "contentSceneLabel": self.blogger.note_scene or None,
            "kolInfoConsumBehaviorLabel": self.blogger.consumer_behavior or None,
            "industrySpecificCrowdsMotorDom": self.blogger.industry_crowd or None,
            "gender": self.blogger.gender,
            "location": self.blogger.location or None,
            "signed": self.blogger.signed,
            "fansAge": self.fans.age,
            "fansGender": self.fans.gender,
            "fansLocation": fans_locations or self.fans.location or None,
            "fansMaritalStatus": self.fans.marital_status,
            "fansConsumptionLevel": self.fans.consumption_level,
            "fansChildAgeInfo": self.fans.child_age or None,
            "fansDevicePrice": self.fans.device_price or None,
            "fansDeviceBrand": self.fans.device_brand or None,
            "noteType": self.note.note_type,
            "tradeType": self.coop.industry,
            "tradeReportBrandIdSet": self.coop.brand_ids or None,
            "excludedTradeReportBrandId": self.coop.exclude_brands,
            "inStar": int(self.flags.is_star) if self.flags.is_star is not None else None,
            "newHighQuality": int(self.flags.new_high_quality) if self.flags.new_high_quality is not None else None,
            "filterIntention": self.flags.filter_intention,
            "firstIndustry": self.flags.industry_first,
            "secondIndustry": self.flags.industry_second,
            "activityCodes": self.flags.activity_codes or None,
            "excludeLowActive": self.flags.exclude_low_active,
            "fansNumUp": int(self.flags.exclude_fans_down) if self.flags.exclude_fans_down is not None else None,
            "excludedTradeReportBrand": self.flags.exclude_cooperated,
            "excludedTradeInviteReportBrand": self.flags.exclude_invited,
        }
        payload.update({key: value for key, value in optional.items() if value is not None})

        ranges = {
            "accumCommonImpMedinNum30d": self.note.imp_median,
            "readMidNor30": self.note.read_median,
            "interMidNor30": self.note.inter_median,
            "progressOrderCnt": self.coop.order_count,
            "accumCoopImpMedinNum30d": self.coop.imp_median,
            "readMidCoop30": self.coop.read_median,
            "interMidCoop30": self.coop.inter_median,
            "mCpuvNum30d": self.coop.cpuv,
            "estimateCpuv30d": self.coop.estimate_cpuv,
            "estimatePictureCpm": self.coop.pic_cpm,
            "estimateVideoCpm": self.coop.video_cpm,
            "estimatePicReadPrice": self.coop.pic_read_price,
            "estimateVideoReadPrice": self.coop.video_read_price,
            "estimatePictureEngageCost": self.coop.pic_engage_cost,
            "estimateVideoEngageCost": self.coop.video_engage_cost,
        }
        for key, value in ranges.items():
            if value is not None:
                payload[key] = value.upstream()
        if self.note.thousand_like_percent is not None:
            payload["thousandLikePercent30"] = self.note.thousand_like_percent.upstream(percent=True)
        if self.coop.reply_48h_ratio is not None:
            payload["inviteReply48hNumRatio"] = self.coop.reply_48h_ratio.upstream(percent=True)
        if self.fans.count is not None:
            lower, upper = self.fans.count.upstream()
            payload["fansNumberLower"] = lower
            payload["fansNumberUpper"] = upper
        if self.coop.pic_price is not None:
            lower, upper = self.coop.pic_price.upstream()
            payload["notePriceLower"] = lower
            payload["notePriceUpper"] = upper
        if self.coop.video_price is not None:
            lower, upper = self.coop.video_price.upstream()
            payload["videoPriceLower"] = lower
            payload["videoPriceUpper"] = upper

        flag_list: list[dict[str, str]] = []
        if self.flags.note_and_live is not None:
            flag_list.append(
                {"flagType": "HAS_BRAND_COOP_BUYER_AUTH", "flagValue": str(int(self.flags.note_and_live))}
            )
        if self.flags.high_quality is not None:
            flag_list.append(
                {"flagType": "IS_HIGH_QUALITY", "flagValue": str(int(self.flags.high_quality))}
            )
        if flag_list:
            payload["flagList"] = flag_list

        live_ranges = {
            "kliveCnt30d": self.live.live_count,
            "avgLiveViewerNum": self.live.avg_viewer,
            "avgAgmv90d": self.live.avg_gmv,
        }
        filter_list = [
            {"field": key, "value": value.upstream()}
            for key, value in live_ranges.items()
            if value is not None
        ]
        if filter_list:
            payload["filterList"] = filter_list
        return payload


def pgy_business_data(envelope: dict[str, Any]) -> Any:
    return envelope.get("data")


def pgy_envelope(data: Any) -> dict[str, Any]:
    return {"code": 0, "msg": "success", "success": True, "data": data}


def tree_paths_by_name(nodes: list[Any], names: list[str]) -> list[str]:
    wanted = set(names)
    matches: list[str] = []

    def walk(items: list[Any], ancestors: list[str]) -> None:
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("label") or item.get("code") or "").strip()
            if not name:
                continue
            path = [*ancestors, name]
            if name in wanted:
                rendered = " ".join(path)
                if rendered not in matches:
                    matches.append(rendered)
            children = item.get("children")
            if isinstance(children, list):
                walk(children, path)

    walk(nodes, [])
    for name in names:
        if not any(path == name or path.endswith(f" {name}") for path in matches):
            matches.append(name)
    return matches
