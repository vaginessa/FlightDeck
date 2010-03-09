
/* 
 * File: Flightdeck.Roar.js
 */

/* 
 * Extending Roar possibilities
 */
Roar = Class.refactor(Roar, {
	reposition: function() {
		var max = document.getCoordinates(), scroll = document.getScroll(), margin = this.options.margin;
		max.left += scroll.x;
		max.right += scroll.x;
		max.top += scroll.y;
		max.bottom += scroll.y;
		var rel = ($type(this.container) == 'element') ? this.container.getCoordinates() : max;
		var left;
		if (this.position.x == 'right') {
			left = (Math.min(rel.right, max.right) - margin.x);
		} else if (this.position.x == 'center') {
			// TODO: HACK: 140 is half of the box width
			left = Math.round((Math.min(rel.right, max.right) / 2 - 140));
		} else {
			left = (Math.max(rel.left, max.left) + margin.x);
		}
		var fromtop = (this.position.y == 'bottom')
				? (Math.min(rel.bottom, max.bottom) - margin.y)
				: (Math.max(rel.top, max.top) + margin.y);


		this.moveTo({
			left: left,
			top: fromtop
		});
	}
	
});

/*
 * Extending Flightdeck with Roar messages
 */

FlightDeck = Class.refactor(FlightDeck,{
	initialize: function(options) {
		this.setOptions(options);
		this.previous(options);
		
		this.warning = new Roar({
			className: 'roar warning',
			position: 'topCenter',
		});
		this.error = new Roar({
			position: 'topLeft',
			className: 'roar error',
			duration: 5000
		});
		this.message = new Roar({
			position: 'topRight',
			className: 'roar message'
		});
		this.parseMessages();
	},
	/*
	 * Method: parseMessages
	 * Parses DOM to find elements with fd_{type_of_message} 
	 * displays messages and removes elements from DOM
	 */
	parseMessages: function() {
		['message', 'warning', 'error'].each(function(t) {
			$$('.fd_'+t).each(function(el) {
				this[t].alert(el.get('title') || t, el.get('text'));
				el.destroy();
			}, this);
		}, this);
	}

});