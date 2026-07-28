# NX 2412
# Journal created by Cai on Sat Jun 27 11:29:04 2026 中国标准时间

#
import math
import NXOpen
import NXOpen.Features
import NXOpen.GeometricUtilities
def main(args) :

    theSession  = NXOpen.Session.GetSession() #type: NXOpen.Session
    workPart = theSession.Parts.Work
    displayPart = theSession.Parts.Display
    # ----------------------------------------------
    #   菜单：插入(S)->设计特征(E)->块(K)...
    # ----------------------------------------------
    markId1 = theSession.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "开始")

    blockFeatureBuilder1 = workPart.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)

    targetBodies1 = [NXOpen.Body.Null] * 1
    targetBodies1[0] = NXOpen.Body.Null
    blockFeatureBuilder1.BooleanOption.SetTargetBodies(targetBodies1)

    blockFeatureBuilder1.BooleanOption.Type = NXOpen.GeometricUtilities.BooleanOperation.BooleanType.Create

    targetBodies2 = [NXOpen.Body.Null] * 1
    targetBodies2[0] = NXOpen.Body.Null
    blockFeatureBuilder1.BooleanOption.SetTargetBodies(targetBodies2)

    blockFeatureBuilder1.BooleanOption.Type = NXOpen.GeometricUtilities.BooleanOperation.BooleanType.Create

    theSession.SetUndoMarkName(markId1, "块 对话框")

    coordinates1 = NXOpen.Point3d(0.0, 0.0, 0.0)
    point1 = workPart.Points.CreatePoint(coordinates1)

    blockFeatureBuilder1.OriginPoint = point1

    unit1 = workPart.UnitCollection.FindObject("MilliMeter")
    expression1 = workPart.Expressions.CreateSystemExpressionWithUnits("0", unit1)

    markId2 = theSession.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "块")

    theSession.DeleteUndoMark(markId2, None)

    markId3 = theSession.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "块")

    blockFeatureBuilder1.Type = NXOpen.Features.BlockFeatureBuilder.Types.OriginAndEdgeLengths

    blockFeatureBuilder1.OriginPoint = point1

    originPoint1 = NXOpen.Point3d(0.0, 0.0, 0.0)
    blockFeatureBuilder1.SetOriginAndLengths(originPoint1, "100", "60", "40")

    blockFeatureBuilder1.SetBooleanOperationAndTarget(NXOpen.Features.Feature.BooleanType.Create, NXOpen.Body.Null)

    feature1 = blockFeatureBuilder1.CommitFeature()

    theSession.DeleteUndoMark(markId3, None)

    theSession.SetUndoMarkName(markId1, "块")

    blockFeatureBuilder1.Destroy()

    workPart.MeasureManager.SetPartTransientModification()

    workPart.Expressions.Delete(expression1)

    workPart.MeasureManager.ClearPartTransientModification()

    # ----------------------------------------------
    #   菜单：工具(T)->自动化(A)->操作记录(J)->停止录制(S)
    # ----------------------------------------------

if __name__ == '__main__':
    main(sys.argv[1:])
