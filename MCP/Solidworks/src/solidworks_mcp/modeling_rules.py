"""Reusable planning rules. Offline review never certifies resulting CAD geometry."""
from __future__ import annotations
from copy import deepcopy
import math
import os
import re
from .contracts import ContractError, require_finite, require_text

LABELS = {"new_part":"零件", "sketch":"轮廓草图", "boss_extrude":"凸台拉伸",
          "boss_revolve":"旋转实体", "cut_extrude":"拉伸切除", "cut_loft":"放样切除",
          "reference_plane_points":"空间基准面", "reference_plane_offset":"偏置基准面",
          "reference_axis":"参考轴", "circular_pattern":"圆周阵列", "fillet":"圆角",
          "chamfer":"倒角", "extrude":"拉伸"}
SYSTEM_PLANES={"Front Plane","Top Plane","Right Plane","前视基准面","上视基准面","右视基准面"}

def prepare_feature_graph(graph):
    """Keep graph IDs stable while resolving all graph references to native display names."""
    if not isinstance(graph,dict) or not isinstance(graph.get("features"),list):
        raise ContractError("feature_graph must contain a features array")
    stack=[(graph,0)];count=0
    while stack:
        value,depth=stack.pop();count+=1
        if count>50000 or depth>32:raise ContractError("Feature Graph exceeds node/depth budget")
        if isinstance(value,dict):stack.extend((v,depth+1) for v in value.values())
        elif isinstance(value,(list,tuple)):stack.extend((v,depth+1) for v in value)
    result=deepcopy(graph)
    metadata=result.get("metadata",{})
    if not isinstance(metadata,dict):raise ContractError("metadata must be an object")
    language=metadata.get("tree_language",os.getenv("SOLIDWORKS_FEATURE_LANGUAGE","preserve"))
    aliases,used={},set()
    for index,feature in enumerate(result["features"],1):
        if not isinstance(feature,dict):raise ContractError("Each feature must be an object")
        identifier=require_text(feature.get("name"),"feature ID")
        if identifier in aliases:raise ContractError("Feature IDs must be unique")
        if "display_name" in feature:
            display=require_text(feature["display_name"],"display_name")
        elif language=="zh-CN" and not re.search(r"[\u4e00-\u9fff]",identifier):
            display=f"{LABELS.get(feature.get('kind'),'特征')}{index:03d}"
        else:display=identifier
        if any(c in display for c in "@\r\n\x00"):
            raise ContractError("Feature display name contains a dimension separator or control character")
        if language=="zh-CN" and not re.search(r"[\u4e00-\u9fff]",display):
            raise ContractError("中文模式下 display_name 必须包含中文")
        if display in used:raise ContractError("Native feature display names must be unique")
        if identifier in SYSTEM_PLANES or display in SYSTEM_PLANES:
            raise ContractError("New feature names cannot shadow a built-in reference plane")
        aliases[identifier]=display;used.add(display)
    for feature in result["features"]:
        identifier=feature["name"].strip()
        feature["name"]=aliases[identifier]
        feature["internal_id"]=identifier
        for field in ("plane","base_plane","sketch","axis","feature"):
            if field in feature and isinstance(feature[field],str):feature[field]=aliases.get(feature[field],feature[field])
        for field in ("profiles","planes"):
            if isinstance(feature.get(field),list):feature[field]=[aliases.get(v,v) if isinstance(v,str) else v for v in feature[field]]
    return result,aliases,language

def plane_frame(points):
    if not isinstance(points,list) or len(points)!=3 or any(len(p)!=3 for p in points):
        raise ContractError("A plane needs three 3D points")
    pts=[[require_finite(x,"plane coordinate") for x in p] for p in points]
    a=[pts[1][i]-pts[0][i] for i in range(3)];b=[pts[2][i]-pts[0][i] for i in range(3)]
    la,lb=math.hypot(*a),math.hypot(*b)
    if min(la,lb)<1e-9:raise ContractError("Plane points must be distinct")
    u=[x/la for x in a];v=[x/lb for x in b]
    cross=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
    sine=math.hypot(*cross)
    if sine<1e-6:raise ContractError("Plane points are collinear or numerically ill-conditioned")
    n=[x/sine for x in cross]
    y=[n[1]*u[2]-n[2]*u[1],n[2]*u[0]-n[0]*u[2],n[0]*u[1]-n[1]*u[0]]
    return {"origin_mm":pts[0],"x_axis":u,"y_axis":y,"normal":n,"conditioning_sine":sine,
            "associative":False}

def validate_sketch_transform(matrix):
    if len(matrix)!=16:raise ContractError("Expected a 16-value SolidWorks transform")
    m=[require_finite(x,"sketch transform") for x in matrix]
    if m[12]<=0:raise ContractError("Sketch transform scale must be positive")
    rows=[m[i:i+3] for i in (0,3,6)]
    for i in range(3):
        for j in range(3):
            if abs(sum(a*b for a,b in zip(rows[i],rows[j]))-(1.0 if i==j else 0.0))>1e-6:
                raise ContractError("Sketch transform rotation is not orthonormal")
    determinant=(m[0]*(m[4]*m[8]-m[5]*m[7])-m[1]*(m[3]*m[8]-m[5]*m[6])+m[2]*(m[3]*m[7]-m[4]*m[6]))
    return {"scale":m[12],"handedness":"right" if determinant>0 else "left"}

def review_feature_graph(graph,plan=None):
    prepared,aliases,language=prepare_feature_graph(graph)
    if plan is None:
        from .feature_graph import compile_feature_graph
        plan=compile_feature_graph(graph)
    frames={s["name"]:plane_frame(s["points_mm"]) for s in plan if s["operation"]=="reference_plane_points"}
    sketches={s["name"]:s for s in plan if s["operation"]=="create_sketch"}
    findings=[]
    for step in plan:
        if step["operation"]=="cut_extrude":
            sketch=sketches[step["sketch"]];frame=frames.get(sketch["plane"])
            if frame and sum(abs(x)>1e-8 for x in frame["normal"])>1 and not step["through_all"]:
                findings.append({"code":"FINITE_OBLIQUE_CUT","feature":step["name"],
                    "required_evidence":["近端/远端截面","侧边界与目标壁面全深度一致性","局部残料/过切检查"],
                    "guidance":"角度正确不代表切除体边界正确；必要时改变方向引用、扩大安全切除区域或使用对应截面放样。"})
        if step["operation"]=="cut_loft":
            findings.append({"code":"LOFT_CORRESPONDENCE","feature":step["name"],
                "required_evidence":["截面顶点对应和闭合方向","中间截面无扭转","目标交线与相邻壁面连续"]})
    if any(s["operation"]=="fillet" for s in plan) and any(s["operation"]=="chamfer" for s in plan):
        findings.append({"code":"FINISHING_INTERACTION","required_evidence":["选边稳定性","圆角/倒角交叉区局部拓扑"],
                         "guidance":"按依赖和设计意图安排顺序；轮廓圆角可前置，非关键边缘修饰可后置。"})
    return {"scope":"offline_planning_only","status":"REVIEW_REQUIRED" if findings else "PLAN_CHECKED",
            "geometry_verified":False,"tree_language":language,"name_map":aliases,"plane_frames":frames,
            "findings":findings,"verification_layers":["重建/特征错误","实体数/尺寸/体积","局部截面/交界拓扑","磁盘回读与导出对照"]}
