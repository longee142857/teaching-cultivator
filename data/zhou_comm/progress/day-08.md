# Day 08
- db: integrity_check: ok
- pages / paragraphs / atoms / atom_spans / atom_l3 / terms : 433 / 6532 / 411 / 1464 / 581 / 1305
- 本批：补齐 Day8 全量 — 修复并重插 Ch10 被拒 7 条；新插 Ch4（38）+ Ch7（42）；保留已入库的 Ch8/Ch10(15)/Ch11（不重插）
- created_day=8 合计 atoms：140；Day1–7 未改动：40 / 35 / 38 / 36 / 48 / 38 / 36

## 插入结果

| file / batch | drafted | inserted | rejected |
|--------------|---------|----------|----------|
| day08_ch8_atoms.json（先前） | 23 | 23 | 0 |
| day08_ch10_atoms.json（先前） | 22 | 15 | 7（core>6） |
| day08_ch10_rejected_fixed.json（本日） | 7 | 7 | 0 |
| day08_ch11_atoms.json（先前） | 15 | 15 | 0 |
| day08_ch4_atoms.json | 38 | 38 | 0 |
| day08_ch7_atoms.json | 42 | 42 | 0 |
| **Day8 合计** | — | **140** | **0（最终）** |

### Ch10 缩核说明（≤6 role=core）
- `zhou.ch10.pn.sync.capture.track`：demote p346.s11、p349.s03 → context
- `zhou.ch10.walsh.hadamard`：demote p350.s15 → context
- `zhou.ch10.walsh.props.caveat`：demote p351.s13（节标题）→ context
- `zhou.ch10.ds.bpsk`：demote p354.s06、p354.s07 → context
- `zhou.ch10.dsss.anti.interference`：demote p358.s01 → context
- `zhou.ch10.ocdm.cdma`：demote p361.s13、p362.s01 → context
- `zhou.ch10.scramble.lfsr.selfsync`：demote p364.s06 → context

## SQL 分章计数（created_day=8）
- Ch4：atoms=38；有 role=core：38（100.0%）；L3 已映射：38；count gate≥25 ✓；core gate ✓
- Ch7：atoms=42；有 role=core：42（100.0%）；L3 已映射：42；count gate≥25 ✓；core gate ✓
- Ch8：atoms=23；有 role=core：23（100.0%）；L3 已映射：23；count gate≥25 ✗；core gate ✓
- Ch10：atoms=22；有 role=core：22（100.0%）；L3 已映射：22；count gate≥25 ✗；core gate ✓
- Ch11：atoms=15；有 role=core：15（100.0%）；L3 已映射：15；count gate≥25 ✗；core gate ✓
- Day8 合计 atoms：140

## 全库 totals
### by created_day
- Day1: 40
- Day2: 35
- Day3: 38
- Day4: 36
- Day5: 48
- Day6: 38
- Day7: 36
- Day8: 140
### by chapter
- Ch2: 38
- Ch3: 36
- Ch4: 38
- Ch5: 40
- Ch6: 73
- Ch7: 42
- Ch8: 23
- Ch9: 84
- Ch10: 22
- Ch11: 15

## L3 覆盖
- syllabus L3 ids：150
- DB 已映射 distinct ∩ syllabus：148
- coverage：98.67%
- 缺失 L3：`comm.analog_mod.nbfm`, `comm.baseband.opt.corr`

## 门禁 / QA
- Ch4/Ch7：atoms≥25 ✓；core 100% ✓
- Ch8/Ch10/Ch11：单章 count gate 仍 <25（章节体量/计划如此）；core 100% ✓
- 抽检：qa/sample-day-08.json（10 atoms，seed=20260908，all_pass=true；均含 print_page + paragraph_ids）
- 教学合并：未合并

## Day8 atom ids（按章）

### Ch4（38）
- `zhou.ch4.am.efficiency`
- `zhou.ch4.am.envelope.demod`
- `zhou.ch4.am.overmod.caveat`
- `zhou.ch4.am.signal.modindex`
- `zhou.ch4.angle.inst.freq`
- `zhou.ch4.carrier.costas.square`
- `zhou.ch4.carrier.pilot`
- `zhou.ch4.carrier.sine.def`
- `zhou.ch4.coherent.demod.principle`
- `zhou.ch4.dsb.sc.gen`
- `zhou.ch4.dsb.spectrum.bw`
- `zhou.ch4.fdm.concept`
- `zhou.ch4.fdm.stereo.fm`
- `zhou.ch4.fm.bessel.spectrum`
- `zhou.ch4.fm.carson`
- `zhou.ch4.fm.discriminator`
- `zhou.ch4.fm.mod.index`
- `zhou.ch4.mod.purposes`
- `zhou.ch4.nf.cascade.friis`
- `zhou.ch4.nf.definition`
- `zhou.ch4.nf.equiv.noise.bw`
- `zhou.ch4.nf.equiv.temp`
- `zhou.ch4.nf.passive.loss`
- `zhou.ch4.nf.receiver.n0`
- `zhou.ch4.noise.am.coherent`
- `zhou.ch4.noise.am.envelope`
- `zhou.ch4.noise.dsb.coherent`
- `zhou.ch4.noise.fm.snr`
- `zhou.ch4.noise.ssb.coherent`
- `zhou.ch4.noise.system.model`
- `zhou.ch4.pm.fm.relation`
- `zhou.ch4.ssb.coherent.out`
- `zhou.ch4.ssb.concept`
- `zhou.ch4.ssb.hilbert.time`
- `zhou.ch4.ssb.implement.caveat`
- `zhou.ch4.sync.phase.error`
- `zhou.ch4.tone.pm.fm.example`
- `zhou.ch4.vsb.filter.condition`

### Ch7（42）
- `zhou.ch7.alaw.mulaw`
- `zhou.ch7.bandpass.sampling`
- `zhou.ch7.coding.efficiency`
- `zhou.ch7.digitization.three.steps`
- `zhou.ch7.distortion.measure`
- `zhou.ch7.effectiveness.reliability.split`
- `zhou.ch7.entropy.chain.rule`
- `zhou.ch7.entropy.h.def`
- `zhou.ch7.entropy.props`
- `zhou.ch7.entropy.units`
- `zhou.ch7.entropy.vs.info.amount`
- `zhou.ch7.fixed.length.theorem`
- `zhou.ch7.hartley.measure`
- `zhou.ch7.huffman.caveat`
- `zhou.ch7.huffman.coding`
- `zhou.ch7.joint.cond.entropy`
- `zhou.ch7.limited.distortion.theorem`
- `zhou.ch7.lowpass.sampling.theorem`
- `zhou.ch7.mutual.info.def`
- `zhou.ch7.mutual.info.props`
- `zhou.ch7.noiseless.coding.goal`
- `zhou.ch7.nonuniform.best.quantizer`
- `zhou.ch7.pcm.encoding`
- `zhou.ch7.pcm.tdm`
- `zhou.ch7.prediction.coding`
- `zhou.ch7.rd.function.def`
- `zhou.ch7.rd.function.props`
- `zhou.ch7.rd.idea`
- `zhou.ch7.redundancy.compression.premise`
- `zhou.ch7.scalar.quantization`
- `zhou.ch7.self.info`
- `zhou.ch7.shannon.inequality`
- `zhou.ch7.source.coding.purpose`
- `zhou.ch7.source.discrete.continuous`
- `zhou.ch7.source.discrete.single.model`
- `zhou.ch7.source.memoryless`
- `zhou.ch7.source.vs.channel.roles`
- `zhou.ch7.transform.coding.kl.dct`
- `zhou.ch7.typical.sequences`
- `zhou.ch7.uniform.quantizer`
- `zhou.ch7.variable.length.theorem`
- `zhou.ch7.vector.quantization`

### Ch8（23）
- `zhou.ch8.additive.interference.classes`
- `zhou.ch8.cap.awgn.symbol`
- `zhou.ch8.cap.bsc.formula`
- `zhou.ch8.cap.definition.coding.theorem`
- `zhou.ch8.cap.infinite.bw.eb.min`
- `zhou.ch8.cap.shannon.bandwidth.snr`
- `zhou.ch8.channel.const.examples`
- `zhou.ch8.channel.const.vs.random`
- `zhou.ch8.channel.continuous.discrete`
- `zhou.ch8.channel.narrow.broad`
- `zhou.ch8.channel.random.multipath.examples`
- `zhou.ch8.continuous.model.addnoise`
- `zhou.ch8.discrete.channel.bsc.matrix`
- `zhou.ch8.diversity.combining`
- `zhou.ch8.diversity.methods`
- `zhou.ch8.diversity.principle.independence`
- `zhou.ch8.fade.coh.time.doppler`
- `zhou.ch8.fade.delay.spread.coh.bw`
- `zhou.ch8.fade.flat.rayleigh.rician`
- `zhou.ch8.fade.flat.vs.freq.selective`
- `zhou.ch8.fade.tv.impulse.response`
- `zhou.ch8.undistorted.envelope.groupdelay`
- `zhou.ch8.undistorted.waveform`

### Ch10（22）
- `zhou.ch10.ds.bpsk`
- `zhou.ch10.ds.ortho.m_ary`
- `zhou.ch10.dsss.anti.interference`
- `zhou.ch10.dsss.bandwidth.gain`
- `zhou.ch10.gold.code`
- `zhou.ch10.lfsr.char.poly`
- `zhou.ch10.mseq.acf.bivalued`
- `zhou.ch10.mseq.balance.run.shift`
- `zhou.ch10.mseq.lfsr.gen`
- `zhou.ch10.mseq.waveform.acf`
- `zhou.ch10.ocdm.cdma`
- `zhou.ch10.pn.def`
- `zhou.ch10.pn.sync.capture.track`
- `zhou.ch10.rake.finger.merge`
- `zhou.ch10.rake.idea`
- `zhou.ch10.rake.vs.multipath`
- `zhou.ch10.scramble.lfsr.selfsync`
- `zhou.ch10.scramble.purpose`
- `zhou.ch10.ss.def`
- `zhou.ch10.walsh.hadamard`
- `zhou.ch10.walsh.improved.pn`
- `zhou.ch10.walsh.props.caveat`

### Ch11（15）
- `zhou.ch11.flat.vs.freq.select`
- `zhou.ch11.ofdm.bpsk.structure`
- `zhou.ch11.ofdm.cp.circular.conv`
- `zhou.ch11.ofdm.cp.def`
- `zhou.ch11.ofdm.dab.example`
- `zhou.ch11.ofdm.fft.ifft.impl`
- `zhou.ch11.ofdm.freq.offset.ici`
- `zhou.ch11.ofdm.guard.blank.ici`
- `zhou.ch11.ofdm.ici.power.scaling`
- `zhou.ch11.ofdm.idea`
- `zhou.ch11.ofdm.ifft.idft`
- `zhou.ch11.ofdm.papr`
- `zhou.ch11.ofdm.qam.envelope`
- `zhou.ch11.ofdm.spacing.2d`
- `zhou.ch11.ofdm.txrx.interleave`

- 阻塞：无
- 合并状态: 未合并
