#!/usr/bin/env python3
"""Executive savings model for the video transit report.

Measured results (docs/video-transit-report.json) x an illustrative monthly
workload (W) x low/high market prices (P). Replace W and P with real volumes
and contracted rates, then run:  python3 docs/savings-model.py
"""
import json
r=json.load(open(__import__('os').path.join(__import__('os').path.dirname(__file__), 'video-transit-report.json')))
vod={(v['source'],v['codec']):v for v in r['vod']}
sweep={s['path']:s for s in r['sweep']}
GBh=lambda kbps: kbps*1000*3600/8/1e9   # GB per hour at kbps
P=dict(egress=(0.01,0.05), region=(0.02,0.09), cpu=(0.02,0.05), store=(0.004,0.023), transit=(0.10,0.50))
W=dict(viewer_hours=1_000_000, constrained_share=0.30, motion_share=0.25, fact_syncs=30, images=10_000_000,
       live_channel_hours=2_000, motion_content_hours=500, archive_hours=10_000, region_gbps=10)
out={}
# A adaptive ladder (mobile)
k720=sweep['regional']['before']['actual_kbps']; k540=sweep['mobile']['before']['actual_kbps']
gbA=(GBh(k720)-GBh(k540))*W['viewer_hours']*W['constrained_share']
out['A_ladder']=dict(k720=k720,k540=k540,pct=1-k540/k720,gb=gbA,usd=[gbA*p for p in P['egress']],
  ssim=(sweep['regional']['after']['quality']['ssim'],sweep['mobile']['after']['quality']['ssim']))
# B AV1 high motion
h=vod[('motion','H264')]; a=vod[('motion','AV1')]
gbB=(GBh(h['before']['actual_kbps'])-GBh(a['before']['actual_kbps']))*W['viewer_hours']*W['motion_share']
cpu_h=4/h['before']['encode_speed_x']; cpu_a=4/a['before']['encode_speed_x']  # CPU-hours per content hour (4 cores)
enc_extra=(cpu_a-cpu_h)*W['motion_content_hours']
out['B_av1']=dict(kh=h['before']['actual_kbps'],ka=a['before']['actual_kbps'],pct=1-a['before']['actual_kbps']/h['before']['actual_kbps'],gb=gbB,
  usd=[gbB*p for p in P['egress']], ssim=(h['after']['quality']['ssim'],a['after']['quality']['ssim']), enc_extra_cpuh=enc_extra,
  enc_cost=[enc_extra*p for p in P['cpu']], net=[gbB*e-enc_extra*c for e,c in zip(P['egress'],P['cpu'])])
# C fact sync
per_rec=272227/242; raw=149e6*per_rec/1e9; z=raw/6.7
gbC=(raw-z)*W['fact_syncs']
out['C_facts']=dict(raw_gb=raw,zstd_gb=z,gb=gbC,usd=[gbC*p for p in P['region']],hours_100mbps=(raw*8/0.1/3600, z*8/0.1/3600))
# D images
png=491.3*1024; webp=53.1*1024
gbD=(png-webp)*W['images']/1e9
out['D_images']=dict(gb=gbD,usd=[gbD*p for p in P['egress']])
# E live repackage vs transcode
rep=[l['after'].get('repackaged') for l in r['live'] if l['after'].get('repackaged')][0]
live_s=r['config']['live_seconds']
copy_cpu_per_s=(rep['hls']['repackage_ms']+rep['dash']['repackage_ms'])/1000/live_s
hls=[p for p in r['packages'] if p['kind']=='HLS'][0]
trans_cpu_per_s=4/hls['before']['encode_speed_x']
cpuE=(trans_cpu_per_s-copy_cpu_per_s)*W['live_channel_hours']
out['E_repack']=dict(copy=copy_cpu_per_s,trans=trans_cpu_per_s,cpuh=cpuE,usd=[cpuE*p for p in P['cpu']])
# F overhead cost (VOD delivered through nodes)
eff=sweep['regional']['during']['framing_efficiency_pct']; ack=sweep['regional']['during']['ack_overhead_pct']
vol=GBh(k720)*W['viewer_hours']
ovh=vol*(100/eff-1)
out['F_overhead']=dict(eff=eff,ack=ack,vol_gb=vol,ovh_gb=ovh,usd=[ovh*p for p in P['region']])
# G signing
sign_ms=[e for e in r['envelope'] if 'Ed25519' in e['codec']][0]['decode_ms']
cpuh_per_pb=1e15/65536*sign_ms/1000/3600
out['G_sign']=dict(ms=sign_ms,cpuh_per_pb=cpuh_per_pb,usd=[cpuh_per_pb*p for p in P['cpu']])
# H decode QA per 1000 content hours
out['H_decode']={c:{'cpu_per_s':vod[('studio',c)]['after']['decode']['cpu_per_media_s'],'cpuh_per_1000h':vod[('studio',c)]['after']['decode']['cpu_per_media_s']*1000} for c in ['H264','H265','AV1']}
# I priority: background capacity reclaimed
m=[l for l in r['live'] if l['kind']=='Direct live' and l['mode']=='multi'][0]; s=[l for l in r['live'] if l['kind']=='Direct live' and l['mode']=='single'][0]
bulk=m['during']['competing_bulk_goodput_mbps']; link=r['paths']['long_haul']['mbps']
share=bulk/link; mbps=W['region_gbps']*1000*share
out['I_priority']=dict(live_multi=m['during']['live']['edge_to_node2_ms']['p50'],live_single=s['during']['live']['edge_to_node2_ms']['p50'],
  bulk=bulk,share=share,mbps=mbps,usd=[mbps*p for p in P['transit']], tb_month=mbps*1e6/8*2.592e6/1e12)
# L archive option
st=[v for v in r['sources'].values()]
mez=sum(s['lossless_master_bytes']/s['seconds']*3600 for s in st)/len(st)/1e9
lad=GBh(hls['before']['actual_kbps'])
gbL=(mez-lad)*W['archive_hours']
out['L_archive']=dict(mez_gb_h=mez,ladder_gb_h=lad,gb=gbL,usd=[gbL*p for p in P['store']])
tot=[sum(out[k]['usd'][i] for k in ['A_ladder','D_images','E_repack','C_facts'])+out['B_av1']['net'][i] for i in (0,1)]
out['total_core']=tot
print(json.dumps(out,indent=1,default=lambda x: round(x,3)))
