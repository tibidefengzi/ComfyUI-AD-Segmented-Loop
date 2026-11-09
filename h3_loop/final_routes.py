"""最终加工的只读分支编译和独立合并接口。"""
import asyncio
import copy
import json
from aiohttp import web
from server import PromptServer
from .routes import guarded
from .final_output import describe_record,merge_final,MergeSpecificationError


def linked_node(value,prompt):
    if isinstance(value,list) and len(value)==2 and isinstance(value[1],int) and str(value[0]) in prompt:
        return str(value[0])
    return None


def prepare_final(prompt,final_id,records):
    if not isinstance(prompt,dict): raise ValueError('工作流提交内容无效')
    final_id=str(final_id)
    if prompt.get(final_id,{}).get('class_type')!='AD_FinalSave':
        raise ValueError('请选择最终保存节点')
    visited=set(); previews=set(); visiting=set()
    def visit(identifier):
        if identifier in visiting: raise ValueError('加工分支中存在循环连线')
        if identifier in visited: return
        visiting.add(identifier)
        node=prompt[identifier]
        if node.get('class_type')=='AidenH3VideoPreview':
            previews.add(identifier)
        else:
            if node.get('class_type') in {'AidenH3Segment','AidenH3AudioQueue','AidenH3Commit'}:
                raise ValueError('最终加工分支仍连接原生成上下文；请只从预览媒体口接入处理链')
            for value in node.get('inputs',{}).values():
                parent=linked_node(value,prompt)
                if parent is not None: visit(parent)
        visiting.remove(identifier);visited.add(identifier)
    visit(final_id)
    if len(previews)!=1:
        raise ValueError('加工所选需要且只能连接一个分段预览来源；请从分段预览媒体口接入处理链后点击加工所选')
    if not isinstance(records,list) or not records: raise ValueError('请先在来源预览中单击或Ctrl选择成果')
    resolved=[describe_record(record) for record in records]
    if len({r['kind'] for r in resolved})!=1:
        raise ValueError('同一次加工请选择同一分类的图片、音频或视频')
    source_id=next(iter(previews))
    # 内部只读节点改用独立 id：不再复用分段预览的节点编号，画布不会把预览节点标成“运行中”。
    compiled={identifier:copy.deepcopy(prompt[identifier]) for identifier in visited if identifier!=source_id}
    stub_id=f"__ad_final_selected__{source_id}"
    while stub_id in compiled: stub_id+="_"
    compiled[stub_id]={'class_type':'AD_FinalSelectedMedia','inputs':{'record':json.dumps(resolved[0],ensure_ascii=False)}}
    for node in compiled.values():
        for key,value in list((node.get('inputs') or {}).items()):
            if isinstance(value,list) and len(value)==2 and isinstance(value[1],int) and str(value[0])==source_id:
                node['inputs'][key]=[stub_id,value[1]]
    compiled[final_id]['inputs']['source_record']=json.dumps(resolved[0],ensure_ascii=False)
    # 追加隐藏输出节点：只有加工所选/继续剩余的编译副本才带它，普通排队不会执行最终保存分支。
    sink_id=f"__ad_final_sink__{final_id}"
    while sink_id in compiled: sink_id+="_"
    compiled[sink_id]={'class_type':'AD_FinalSink','inputs':{'value':[final_id,0]}}
    # 原预览的INPUT/上下文与H3祖先不进入此图；原始工作流完全不回写。
    return {'prompt':compiled,'source_id':stub_id,'final_id':final_id,'records':resolved}


routes=PromptServer.instance.routes

@routes.post('/aiden_h3/final/prepare')
@guarded
async def prepare(request):
    data=await request.json()
    result=await asyncio.to_thread(prepare_final,data.get('prompt'),data.get('final_id'),data.get('records'))
    return web.json_response(result)


@routes.post('/aiden_h3/final/merge')
@guarded
async def merge(request):
    data=await request.json()
    try:
        record=await asyncio.to_thread(merge_final,data.get('records') or [],data.get('directory',''),data.get('prefix','最终合并'),data.get('normalize') is True)
    except MergeSpecificationError as error:
        return web.json_response({'error':str(error),'code':'spec_mismatch'},status=409)
    return web.json_response({'record':record})
