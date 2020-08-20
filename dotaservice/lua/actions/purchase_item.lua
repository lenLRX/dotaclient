-------------------------------------------------------------------------------
--- AUTHOR: lenlrx
-------------------------------------------------------------------------------

local PurchaseItem = {}

PurchaseItem.Name = "Purchase Item"
PurchaseItem.NumArgs = 4

-------------------------------------------------
function PurchaseItem:Call( hUnit, iItem, sItemName, iUnit )

    local item_name = sItemName[1]
    hUnit:ActionImmediate_PurchaseItem(item_name)
end
-------------------------------------------------

return PurchaseItem