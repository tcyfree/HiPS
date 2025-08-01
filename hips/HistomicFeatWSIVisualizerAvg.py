import os
from os.path import join as opj
import warnings
from typing import Tuple, List
from pandas import read_csv, Series
import numpy as np
import matplotlib.pylab as plt
from matplotlib.patches import Rectangle
# from histomicstk.preprocessing.color_normalization import \
#     deconvolution_based_normalization
from sklearn.preprocessing import MinMaxScaler

from MuTILs_Panoptic.histolab.src.histolab.types import CoordinatePair
from MuTILs_Panoptic.histolab.src.histolab.slide import Slide
from MuTILs_Panoptic.histolab.src.histolab.util import np_to_pil
import pandas as pd
from openpyxl import load_workbook


class HistomicFeatWSIVisualizer(object):
    """
    Visualize WSI heatmap of histomic features.
    """
    def __init__(
        self,
        perslide_feats_dir: str,
        wsi_dir: str,
        featname_list: List[Tuple[str,str]],
        *,
        savedir: str = None,
        topk: int = 20,
        tile_size: Tuple = (512, 512),
        slide_names: List[str] = None,  # names of slides, no file extension
        color_normalize: bool = False,
        wsi_ext: str = 'svs',
        normalize_features: bool = True,
        _debug=False,
    ):
        if _debug:
            warnings.warn("Running in DEBUG mode!!!")
            raise NotImplementedError("Didn't implement debug mode yet.")

        self._debug = _debug
        self.perslide_feats_dir = perslide_feats_dir
        self.wsi_dir = wsi_dir
        self.featname_list = featname_list
        self.topk = topk
        self.tile_size = tile_size
        self.slide_names = slide_names if slide_names is not None else [
            dc.replace('.csv', '') for dc in os.listdir(perslide_feats_dir)
            if dc.endswith('.csv')
        ]
        self.savedir = savedir if savedir is not None else perslide_feats_dir
        os.makedirs(self.savedir, exist_ok=True)
        self.color_normalize = color_normalize
        self.wsi_ext = wsi_ext
        self.normalize_features = normalize_features

        # variables to carry over. This is not the best way to do this but
        # I'm in a rush now so whatever.
        self._slide = None
        self._slidename = None
        self._featname = None
        self._short_featname = None
        self._thumb = None
        self._sf = None

    @staticmethod
    def _get_coords_from_tilename(name: str):
        """"""
        return CoordinatePair(*[
            int(name.split(f"_{loc}-")[-1].split('_')[0].replace('.json', ''))
            for loc in ['left', 'top', 'right', 'bottom']
        ])

    def _save_tile(self, tidx, tilename, feat_df):
        """"""
        if np.isnan(feat_df[tilename]):
            return

        where = opj(
            self.savedir, self._slidename, f"{self._short_featname}_tiles"
        )
        os.makedirs(where, exist_ok=True)

        coords = self._get_coords_from_tilename(tilename)
        tile = self._slide.extract_tile(
            coords, tile_size=self.tile_size, mpp=0.5
        )
        rgb = tile.image

        # color normalize for comparability
        if self.color_normalize:
            rgb = deconvolution_based_normalization(  # noqa
                np.array(rgb), mask_out=~tile._tissue_mask
            )
            rgb = np_to_pil(rgb)

        # now plot and save
        description = f"rank={tidx}_{self._short_featname}={feat_df[tilename]:.3E}"
        print(f"{self._slidename}: {description}")
        fig, ax = plt.subplots(1, 2, figsize=(2 * 7, 7))
        ax[0].imshow(rgb)
        ax[0].set_title(description)
        ax[1].imshow(self._thumb)
        xmin, ymin, xmax, ymax = [int(j * self._sf) for j in coords]
        ax[1].add_patch(Rectangle(
            xy=(xmin + ((xmax - xmin) // 2), ymin + ((ymax - ymin) // 2)),
            width=xmax - xmin,
            height=ymax - ymin,
            linewidth=2,
            color='yellow',
            fill=False,
        ))
        plt.tight_layout()
        plt.savefig(opj(
            where, f"rank={tidx}__{tilename.replace('.json', '.png')}",
        ))
        plt.close()


    def _compute_average_feature(self, all_feats_df):
        """
        对 featname_list 中每个特征做 MinMax 归一化后求平均，返回带有新列 '__AveragedFeature__' 的 DataFrame。
        """
        normalized_feats = []
        valid_featnames = []

        for featname, _ in self.featname_list:
            if featname not in all_feats_df.columns:
                print(f"Warning: {featname} not found in {self._slidename}.csv")
                continue

            values = all_feats_df[featname].values.reshape(-1, 1)
            # 将值转换为 float，以便支持 NaN 替换
            values = all_feats_df[featname].astype(float).values.reshape(-1, 1)
            # 替换 Inf 为 NaN
            values[np.isinf(values)] = np.nan
            # 去除 NaN 值（保留索引对齐）
            if np.isnan(values).all():
                continue

            # 对每列进行归一化，结果保持索引
            norm_values = MinMaxScaler().fit_transform(values)
            norm_series = pd.Series(norm_values[:, 0], index=all_feats_df.index)
            normalized_feats.append(norm_series)
            valid_featnames.append(featname)

        if not normalized_feats:
            raise ValueError("No valid features found for averaging.")

        # 将所有归一化特征按行拼接，然后求均值
        avg_feat = pd.concat(normalized_feats, axis=1).mean(axis=1)
        all_feats_df["phynotype1"] = avg_feat

        # # ===========保存平均特征到 Excel ===========
        # # 只保留有效特征列 + phynotype6
        # result_df = all_feats_df[valid_featnames + ["phynotype6"]]
        # # 只取每列的均值，构建一个一行的新 DataFrame
        # mean_values = result_df.mean(axis=0).to_frame().T  # 转置为一行
        # mean_values.insert(0, "slide_name", self._slidename)  # 可选：添加来源名（如 slide name）
        # # 保存结果到 Excel 文件
        # output_path = "/home/network/Desktop/Project/MuTILs_HiPS/output/HFVis/IMPRESS/heatmap_avg_phynotype6.xlsx"
        # os.makedirs(os.path.dirname(output_path), exist_ok=True)  # 确保目录存在
        # if os.path.exists(output_path):
        #     # 如果文件存在，加载并追加数据
        #     with pd.ExcelWriter(output_path, engine='openpyxl', mode='a', if_sheet_exists='overlay') as writer:
        #         # 读取已有内容，找到下一个可用行
        #         book = writer.book
        #         sheet = book.active
        #         startrow = sheet.max_row
        #         mean_values.to_excel(writer, index=False, header=False, startrow=startrow)
        # else:
        #     # 文件不存在，则正常保存
        #     mean_values.to_excel(output_path, index=False)
        
        # print(f"Saved to {output_path}")

        return all_feats_df

    def visualize_top_and_bottom_tiles(self, top_salient_feats_df):
        """"""
        feat_df = top_salient_feats_df.loc[:, self._featname].sort_values(
            ascending=False
        )
        feat_df = feat_df.dropna()
        k = min(feat_df.shape[0], self.topk) // 2
        for tidx in (list(range(k)) + list(range(-1, -k-1, -1))):
            self._save_tile(
                tidx=tidx, tilename=feat_df.index[tidx], feat_df=feat_df
            )

    def save_heatmap_for_feat(self, all_feats_df):
        """"""
        savedir = opj(self.savedir, self._slidename)
        os.makedirs(savedir, exist_ok=True)

        # init heatmap masks
        feat_heatmap = np.zeros(
            (self._thumb.size[1], self._thumb.size[0]), dtype=np.float32
        )
        saliency_heatmap = feat_heatmap.copy()

        # heatmap for feature
        finite_feat = all_feats_df.loc[:, self._featname]
        finite_feat = finite_feat[np.isfinite(finite_feat.values)]
        normalized_feat = (
            MinMaxScaler().fit_transform(finite_feat.values.reshape(-1, 1))
            if self.normalize_features else finite_feat.values.reshape(-1, 1)
        )
        normalized_feat = Series(normalized_feat[:, 0], index=finite_feat.index)
        for tilename, feat_value in normalized_feat.items():
            coords = self._get_coords_from_tilename(tilename)
            xmin, ymin, xmax, ymax = [int(j * self._sf) for j in coords]
            feat_heatmap[ymin:ymax, xmin:xmax] = feat_value

        # heatmap for saliency
        top_salient_feats_df = all_feats_df.iloc[:self.topk, :]
        normalized_saliency = MinMaxScaler().fit_transform(
            top_salient_feats_df.loc[:, "Saliency.SaliencyScore"].values.reshape(-1, 1)
        )[:, 0]
        normalized_saliency = Series(
            normalized_saliency, index=top_salient_feats_df.index,
        )
        for tilename, saliency_value in normalized_saliency.items():
            coords = self._get_coords_from_tilename(tilename)
            xmin, ymin, xmax, ymax = [int(j * self._sf) for j in coords]
            saliency_heatmap[ymin:ymax, xmin:xmax] = saliency_value
        # 调整为2个图像
        fig, ax = plt.subplots(
            1,
            3,
            figsize=(5 + 18, 10),
            gridspec_kw={'width_ratios': [25, 25, 1]},
            # sharey='row',
        )

        # rgb for comparison
        ax[0].imshow(self._thumb)

        # heatmap for feature
        # 原图透明度
        ax[1].imshow(self._thumb, alpha=1)
        im = ax[1].imshow(
            np.ma.masked_array(feat_heatmap, feat_heatmap == 0),
            cmap='plasma',
            alpha=0.95,
            vmin=np.min(feat_heatmap),
            vmax=np.max(feat_heatmap),
        )
        ax[1].set_title(self._short_featname)

        fig.colorbar(im, cax=ax[2], orientation='vertical')
        print(f"Saving heatmap for {savedir} - {self._short_featname}...")
        plt.tight_layout()
        plt.savefig(opj(
            savedir, f"{self._short_featname}_HEATMAP_{self._slidename}.png",
        ))
        plt.close()


    def run(self):
        """"""
        for self._slidename in self.slide_names:

            all_feats_df = read_csv(
                opj(self.perslide_feats_dir, f"{self._slidename}.csv"),
                index_col=0
            )
            self._slide = Slide(
                opj(self.wsi_dir, f"{self._slidename}.{self.wsi_ext}"),
                opj(self.wsi_dir, "out", f"{self._slidename}.{self.wsi_ext}"),
                use_largeimage=True,
            )
            # scale factor from base to thumbnail
            self._thumb = self._slide.thumbnail
            self._sf = self._thumb.size[0] / self._slide.dimensions[0]
            # topk salient rois used for feature analysis
            # all_feats_df.sort_values(
            #     "Saliency.SaliencyScore", axis=0, ascending=False, inplace=True
            # )
            # # 1. visualize features one by one
            # for _, (self._featname, self._short_featname) in enumerate(self.featname_list):

            #     self.save_heatmap_for_feat(all_feats_df=all_feats_df)
            #     # self.visualize_top_and_bottom_tiles(
            #     #     top_salient_feats_df=all_feats_df.iloc[:self.topk, :]
            #     # )
            # 2. visualize features by avg
            # Step 1: 平均多个特征
            all_feats_df = self._compute_average_feature(all_feats_df)
            # Step 2: 设置成类变量（方便 heatmap 画图用）
            self._featname = "__AveragedFeature__"
            self._short_featname = "AvgFeat"
            self._featname = "phynotype1"
            self._short_featname = "Ph1"
            # Step 3: 画 heatmap
            self.save_heatmap_for_feat(all_feats_df=all_feats_df)
            self.visualize_top_and_bottom_tiles(top_salient_feats_df=all_feats_df.iloc[:self.topk, :])


# =============================================================================

if __name__ == "__main__":

    import argparse

    # HOME = os.path.expanduser('~')

    parser = argparse.ArgumentParser(
        description='Visualize histomic feature heatmaps using ROI-level data'
    )
    parser.add_argument(
        '--perslidedir', type=str,
        # default=opj(
        #     HOME, 'Desktop', 'STROMAL_IMPACT_ANALYSIS', 'plco_breast',
        #     'perSlideROISummaries',
        # ),
        default = '/home/network/Desktop/Project/MuTILs_HiPS/output/HiPS/IMPRESS/TNBC/cTMEfeats/perSlideROISummaries'
    )
    parser.add_argument(
        '--wsidir', type=str,
        # default=opj(
        #     HOME, 'Desktop', 'STROMAL_IMPACT_ANALYSIS', 'plco_breast', 'wsi',
        # ),
        default = '/home/network/Desktop/Project/MuTILs_HiPS/input/IMPRESS/TNBC'
    )
    parser.add_argument(
        '--savedir', type=str,
        # default=opj(
        #     HOME, 'Desktop', 'STROMAL_IMPACT_ANALYSIS', 'plco_breast', 'HFVis',
        # ),
        default = '/home/network/Desktop/Project/MuTILs_HiPS/output/HFVis/IMPRESS/TNBC_select'
    )
    parser.add_argument('--wsiext', type=str, default='svs')
    ARGS = parser.parse_args()
    # print("ARGS:", ARGS)

    vizer = HistomicFeatWSIVisualizer(
        perslide_feats_dir=ARGS.perslidedir,
        wsi_dir=ARGS.wsidir,
        savedir=ARGS.savedir,
        # phynotype1
        featname_list = [
            ("NuclearStaining.HistEnergy.StromalSuperclass.Mean", "HistEnergyOfStromalNuclei"),
            ("CytoplasmicStaining.Std.StromalSuperclass.Mean", "CytoplasmicStainingStdOfStromalCells"),
            ("CytoplasmicTexture.Mag.Std.StromalSuperclass.Mean", "TextureMagnitudeStdOfStromalCells"),
            ("CytoplasmicTexture.SumOfSquares.Mean.StromalSuperclass.Mean", "SumOfSquaresMeanOfStromalTextures"),
            ("CytoplasmicTexture.SumOfSquares.Range.StromalSuperclass.Mean", "SumOfSquaresRangeOfStromalTextures"),
            ("CytoplasmicTexture.SumAverage.Range.StromalSuperclass.Mean", "SumAverageRangeOfStromalTextures"),
            ("CytoplasmicTexture.SumVariance.Mean.StromalSuperclass.Mean", "SumVarianceMeanOfStromalTextures"),
            ("CytoplasmicTexture.SumOfSquares.Range.StromalSuperclass.Std", "SumOfSquaresRangeStdOfStromalTextures"),
            ("CytoplasmicTexture.SumAverage.Range.StromalSuperclass.Std", "SumAverageRangeStdOfStromalTextures"),
        ],
        # # phynotype2
        # featname_list = [
        #     ("CytoplasmicStaining.MeanMedianDiff.EpithelialSuperclass.Mean", "CytoplasmicMeanMedianDiffOfEpithelialCells"),
        #     ("CytoplasmicStaining.Skewness.EpithelialSuperclass.Mean", "CytoplasmicStainingSkewnessOfEpithelialCells"),
        #     ("CytoplasmicStaining.Mean.StromalSuperclass.Mean", "AverageCytoplasmicStainingOfStromalCells"),
        #     ("CytoplasmicStaining.Mean.TILsSuperclass.Mean", "AverageCytoplasmicStainingOfTILs"),
        #     ("CytoplasmicTexture.SumAverage.Mean.StromalSuperclass.Mean", "SumAverageMeanOfStromalTextures"),
        # ],
        # # phynotype3
        # featname_list = [
        #     ("NoOfNuclei.TILsCell", "NumberOfTILsNuclei"),
        #     ("TILsScore.TILs2AllRatio", "RatioOfTILsToAllCells"),
        #     ("TILsScore.nTILsCells2AnyStromaRegionArea", "TILsCellDensityInStroma"),
        #     ("TILsScore.nTILsCells2nAllCells", "ProportionOfTILs"),
        #     ("RipleysK.Raw.TILsSuperclass.Radius-64", "RipleyKRawTILsRadius64"),
        #     ("RipleysK.Raw.TILsSuperclass.Radius-128", "RipleyKRawTILsRadius128"),
        #     ("RipleysK.Raw.Center-TILsSuperclass-Surround-EpithelialSuperclass.Radius-32", "RipleyKRawCenterTILsSurroundEpithelRadius32"),
        #     ("RipleysK.Raw.Center-TILsSuperclass-Surround-EpithelialSuperclass.Radius-64", "RipleyKRawCenterTILsSurroundEpithelRadius64"),
        #     ("RipleysK.Raw.Center-TILsSuperclass-Surround-EpithelialSuperclass.Radius-128", "RipleyKRawCenterTILsSurroundEpithelRadius128"),
        #     ("RipleysK.Raw.Center-TILsSuperclass-Surround-StromalSuperclass.Radius-32", "RipleyKRawCenterTILsSurroundStromalRadius32"),
        #     ("RipleysK.Raw.Center-TILsSuperclass-Surround-StromalSuperclass.Radius-64", "RipleyKRawCenterTILsSurroundStromalRadius64"),
        #     ("RipleysK.Raw.Center-TILsSuperclass-Surround-StromalSuperclass.Radius-128", "RipleyKRawCenterTILsSurroundStromalRadius128"),
        # ],
        # # phynotype4
        # featname_list = [
        #     ("NuclearTexture.SumAverage.Range.StromalSuperclass.Mean", "SumAverageRangeOfStromalNuclearTextures"),
        #     ("NuclearTexture.DifferenceEntropy.Mean.StromalSuperclass.Mean", "DifferenceEntropyMeanOfStromalNuclearTextures"),
        #     ("NuclearTexture.IMC2.Range.StromalSuperclass.Mean", "IMC2RangeOfStromalNuclearTextures"),
        # ],
        # # phynotype5
        # featname_list = [
        #     ("NuclearTexture.SumEntropy.Range.TILsSuperclass.Mean", "SumEntropyRangeOfTILsNuclearTextures"),
        #     ("NuclearTexture.SumEntropy.Range.TILsSuperclass.Std", "SumEntropyRangeStdOfTILsNuclearTextures"),
        # ],
        # # phynotype6
        # featname_list = [
        #     ("NuclearTexture.DifferenceVariance.Range.StromalSuperclass.Mean", "DifferenceVarianceRangeOfStromalNuclearTextures"),
        # ],
        
        # 指定运行那些slides
        # Ph1
        slide_names = ["917_HE", "987_HE"],
        # Ph2
        # slide_names = ["950_HE", "987_HE"],
        # Ph3
        # slide_names = ["950_HE", "939_HE"],
        # Ph4
        # slide_names = ["917_HE", "939_HE"],
        # Ph5
        # slide_names = ["914_HE", "918_HE"],
        # Ph6
        # slide_names = ["918_HE", "950_HE"],
        wsi_ext=ARGS.wsiext,
    )
    vizer.run()
